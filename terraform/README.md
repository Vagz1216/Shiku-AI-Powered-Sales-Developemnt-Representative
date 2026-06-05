# SDR AWS infrastructure (Terraform)

Independent stacks with **local state** (same pattern as the Alex course): `terraform/*.tfstate` is gitignored—do not commit state.

**Region:** default `eu-west-2` (London). IAM Identity Center can remain in `eu-north-1`; that region is only for workforce login. The application stack uses `eu-west-2` because App Runner is available there.

## Order of deployment

1. **`database/`** — Aurora PostgreSQL Serverless v2 + Secrets Manager secret + Data API enabled.
2. **`backend/`** — ECR repository + App Runner service (expects DB ARNs from step 1).
3. Build and push the API image to ECR, then redeploy App Runner if needed (see project `docs/DEPLOY_AWS.md`).
4. **`frontend/`** — S3 static hosting + CloudFront (proxies `/api/*`, `/webhook`, `/health*`, `/outreach/*` to App Runner).

**Next step once `terraform/database` and Aurora schema are done:** open `terraform/backend`, ensure `terraform.tfvars` exists and is filled, then run `terraform init`, **`terraform plan`**, **`terraform apply`**, and **`terraform output`**.

## Commands (from each stack directory)

```bash
cp terraform.tfvars.example terraform.tfvars   # first time only; then edit values
terraform init
terraform plan    # always review the plan before apply
terraform apply
terraform output
```

Copy outputs forward: database → backend `cluster_arn` / `secret_arn`; backend → frontend `backend_url` (`service_url`).

For full secrets handling, IAM additions beyond Alex days 1–4, and production hardening, see **`docs/DEPLOY_AWS.md`** in the repo root.
