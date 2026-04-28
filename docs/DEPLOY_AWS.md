# Deploying SDR on AWS (us-west-2)

This document aligns with the **Alex** course approach (separate Terraform directories, local state, incremental IAM) while listing what you need **in addition** to guides completed through **day 4**, so the **SDR** stack (Aurora + App Runner + ECR + S3 + CloudFront) can be deployed safely.

## What you already have (assumed)

- IAM user **`ai_agent`** (or equivalent) with permissions established through Alex **guides 1–4** (Bedrock/SageMaker/EventBridge-style setup as covered there).
- AWS CLI configured for that user (`aws sts get-caller-identity`).
- Terraform ≥ 1.5.

## IAM: attach policies for SDR Terraform

Alex day 4 does not cover every service SDR uses. Attach **additional** permissions (custom policy or curated managed policies) so Terraform can create:

| Area | Typical actions |
|------|------------------|
| **RDS / Aurora** | `rds:*` scoped to your account/region, or use managed policies such as broader RDS access for prototyping |
| **Secrets Manager** | `secretsmanager:*` on secrets created for this project |
| **ECR** | `ecr:*` on repository `sdr-backend` |
| **App Runner** | `apprunner:*`, plus pass-role for App Runner service/access roles |
| **IAM** | `iam:CreateRole`, `iam:PutRolePolicy`, `iam:AttachRolePolicy`, `iam:PassRole` for App Runner roles |
| **S3** | Bucket creation and policy for `sdr-frontend-*` |
| **CloudFront** | Create/update distributions and origins |
| **Logs** | CloudWatch Logs as needed by App Runner |

For a **minimum-friction** sandbox, teams sometimes attach **`PowerUserAccess`** plus **`IAMFullAccess`** only while bootstrapping—tighten to resource-scoped policies before production.

The **App Runner instance role** created by Terraform is already scoped to **RDS Data API** + **Secrets Manager** `GetSecretValue` on the DB secret + logging—no extra manual IAM there.

## Region

Use **`us-west-2`** everywhere:

- Default in `terraform/*/variables.tf` is `us-west-2`.
- `export AWS_REGION=us-west-2` (or `AWS_DEFAULT_REGION`) for CLI and for `scripts/apply_aurora_schema.py`.

## Step 1 — Database (`terraform/database`)

```bash
cd terraform/database
cp terraform.tfvars.example terraform.tfvars
terraform init && terraform apply
```

Save **`cluster_arn`**, **`secret_arn`**, **`db_name`** from `terraform output`.

### Apply PostgreSQL schema (Data API)

From the **project root**, with credentials that can call **RDS Data API** on that cluster:

```bash
export AWS_REGION=us-west-2
export DB_CLUSTER_ARN="(terraform output cluster_arn)"
export DB_SECRET_ARN="(terraform output secret_arn)"
export DB_NAME="sdr"

uv run scripts/apply_aurora_schema.py          # schema only
# uv run scripts/apply_aurora_schema.py --seed  # optional demo seed
```

Do **not** rely on SQLite bootstrap on Aurora; the app uses `db/schema_pg.sql` via this step.

**Next step after schema:** deploy the backend stack (ECR + App Runner)—see Step 2 below.

### Important: image must exist before App Runner succeeds

App Runner is configured to pull **`sdr-backend:latest`** from ECR. If that tag does **not** exist yet, creation often ends in **`CREATE_FAILED`**.

**Recommended first-time order**

1. Create **ECR only** (fast), push **`latest`**, then apply **everything**:
   ```bash
   cd terraform/backend
   terraform init
   terraform apply -target=aws_ecr_repository.sdr_backend
   ```
2. Build and push the image (Step 3 commands; use `terraform output -raw ecr_repository_url` after the command above).
3. Create IAM + App Runner:
   ```bash
   terraform apply   # full apply: IAM roles + App Runner service
   ```

Alternatively, run a **full** `terraform apply` only **after** you have already pushed `:latest` to a pre-existing `sdr-backend` repo (same account/region).

## Step 2 — Backend (`terraform/backend`)

Prerequisites: `terraform/database` applied; `terraform/backend/terraform.tfvars` filled with DB ARNs and app secrets (copy from `terraform/backend/terraform.tfvars.example` if needed).

From the **repository root** (after ECR contains **`sdr-backend:latest`**, or use the targeted flow above):

```bash
cd terraform/backend
terraform init
terraform plan    # review: ECR repo, IAM roles, App Runner service
terraform apply   # type yes when prompted
terraform output  # save service_url and ecr_repository_url
```

If you have not created `terraform.tfvars` yet:

```bash
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars: cluster_arn, secret_arn, API keys, Clerk, cors_origins, etc.
```

Sensitive values today are passed as **App Runner environment variables** (Terraform `sensitive` variables). For stricter production posture, migrate secrets to **Secrets Manager** or **Parameter Store** and reference them from App Runner (requires Terraform/App Runner updates).

`terraform/backend` maps to `config/settings.py`: **OpenAI** + fallbacks (**`GROQ_API_KEY`**, **`CEREBRAS_API_KEY`**, **`OPENROUTER_API_KEY`**), **AgentMail**, **Composio** (**`COMPOSIO_API_KEY`**, optional **`COMPOSIO_USER_ID`**), **Clerk**, **`WEBHOOK_SECRET`**, **`CORS_ORIGINS`**, optional **`OPENAI_TRACING_KEY`**, and explicit **`AWS_REGION`** for boto3. Any other non-secret tuning (models, `REQUIRE_HUMAN_APPROVAL`, `DATA_SOURCE`, etc.) goes in **`extra_runtime_environment_variables`** in `terraform.tfvars` (see `terraform/backend/terraform.tfvars.example`).

Set **`cors_origins`** to your **CloudFront HTTPS URL** once step 4 exists (comma-separated list if needed). Until then, you can temporarily use the App Runner URL for testing.

Note **`service_url`** from output (e.g. `https://xxxx.us-west-2.awsapprunner.com`).

### If `terraform apply` fails with App Runner `CREATE_FAILED`

Usually the ECR image was missing. Recover:

1. **Push** `sdr-backend:latest` to ECR (Step 3).
2. **Delete** the failed App Runner service (Console → App Runner → service → Delete), or:
   ```bash
   aws apprunner delete-service --region us-west-2 \
     --service-arn "$(aws apprunner list-services --region us-west-2 --query "ServiceSummaryList[?ServiceName=='sdr-backend'].ServiceArn | [0]" --output text)"
   ```
3. **Remove** the failed resource from Terraform state so it can be recreated:
   ```bash
   cd terraform/backend
   terraform state rm aws_apprunner_service.sdr_backend
   ```
4. Run **`terraform apply`** again.

## Step 3 — Container image (ECR)

Build from repo root (Dockerfile listens on **port 8000**, matching App Runner):

```bash
aws ecr get-login-password --region us-west-2 | docker login --username AWS --password-stdin ACCOUNT_ID.dkr.ecr.us-west-2.amazonaws.com
docker build -t sdr-backend .
docker tag sdr-backend:latest ACCOUNT_ID.dkr.ecr.us-west-2.amazonaws.com/sdr-backend:latest
docker push ACCOUNT_ID.dkr.ecr.us-west-2.amazonaws.com/sdr-backend:latest
```

Trigger an App Runner deployment (console **Deploy**, or `aws apprunner start-deployment` on the service).

## Step 4 — Frontend (`terraform/frontend`)

```bash
cd terraform/frontend
cp terraform.tfvars.example terraform.tfvars
# backend_url = https://....us-west-2.awsapprunner.com from backend output
terraform init && terraform apply
```

### Build Next.js with the right API URL

Pages use `NEXT_PUBLIC_API_URL || 'http://localhost:8000'`. For production behind CloudFront, set the **public site URL** so browser calls hit CloudFront and are routed to App Runner:

```bash
cd frontend
NEXT_PUBLIC_API_URL="https://YOUR_CLOUDFRONT_DOMAIN.cloudfront.net" npm run build
```

The Terraform frontend stack expects a **static upload** to S3. Enable Next static export if you have not already (for example `output: 'export'` in `frontend/next.config.ts`), resolve any App Router constraints that block export, then upload the generated **`out/`** directory to the bucket from `terraform output s3_bucket`. If you prefer a Node server for Next instead of S3, you would replace this layer with Amplify, ECS, or similar—not covered here.

After upload, **invalidate CloudFront**: `aws cloudfront create-invalidation --distribution-id ID --paths "/*"`.

### AgentMail / webhooks

Configure AgentMail (or your provider) **webhook URL** as:

`https://YOUR_CLOUDFRONT_DOMAIN.cloudfront.net/webhook`

so traffic matches the **`/webhook`** CloudFront behavior to App Runner. Keep **`WEBHOOK_SECRET`** aligned with what you configure upstream.

## Security checklist (recommended)

- **HTTPS**: CloudFront default certificate is fine for testing; use **ACM** in **us-east-1** for custom domains with CloudFront (standard AWS requirement).
- **S3**: Current Terraform uses a **public read** bucket for static assets; acceptable for public SPA assets—avoid putting secrets in the bundle. Optionally refactor to **Origin Access Control** and private bucket.
- **WAF**: Optional; see Alex **guide 8** / enterprise patterns for attaching WAF to CloudFront.
- **RDS**: Cluster uses default VPC for simplicity; production workloads often use **private subnets**, **no public RDS**, and **VPC endpoints** or restricted egress.
- **Secrets**: Rotate **`webhook_secret`**, Clerk keys, and LLM keys on a schedule; prefer Secrets Manager over plain tfvars for shared prod state.

## Troubleshooting

- **App Runner unhealthy**: Confirm image exposes **8000**, health path **`/health`**, and instance role allows **RDS Data API** + secret read.
- **CORS errors**: Update **`cors_origins`** in backend Terraform to the exact browser origin (CloudFront URL, including `https`, no trailing slash unless your app sends it).
- **DB errors**: Verify **`DB_CLUSTER_ARN`**, **`DB_SECRET_ARN`**, **`DB_NAME`** in App Runner match `terraform/database` outputs and schema was applied.

## Reference layout

| Directory | Purpose |
|-----------|---------|
| `terraform/database` | Aurora + secret |
| `terraform/backend` | ECR + App Runner |
| `terraform/frontend` | S3 + CloudFront → App Runner |

For Terraform commands and output chaining, see **`terraform/README.md`**.
