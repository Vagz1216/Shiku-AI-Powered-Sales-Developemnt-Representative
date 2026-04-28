-- Seed data for PostgreSQL Aurora

INSERT INTO campaigns (id, name, value_proposition, cta, status) VALUES
  (1, 'Outbound Outreach - Q2', 'Increase pipeline with our AI sales assistant', 'Book a quick demo', 'ACTIVE'),
  (2, 'Re-engagement', 'We have new features you might like', 'Learn more', 'PAUSED'),
  (3, 'SOC2 Compliance Fast-Track', 'Skip months of SOC2 compliance work with our automated solution', 'Get SOC2 ready in weeks', 'ACTIVE'),
  (4, 'DevOps Automation Revolution', 'Cut deployment time by 80% with AI-powered DevOps automation', 'See the demo', 'ACTIVE'),
  (5, 'Cybersecurity Risk Assessment', 'Identify security vulnerabilities before attackers do', 'Start free security scan', 'ACTIVE'),
  (6, 'Sales Pipeline Optimization', 'Double your qualified leads with predictive lead scoring', 'Boost your pipeline', 'ACTIVE'),
  (7, 'Customer Success Automation', 'Reduce churn by 40% with proactive customer health monitoring', 'Improve retention now', 'ACTIVE'),
  (8, 'Financial Analytics Dashboard', 'Make data-driven decisions with real-time financial insights', 'View live dashboard', 'ACTIVE'),
  (9, 'HR Onboarding Streamline', 'Onboard new hires 3x faster with automated workflows', 'Streamline onboarding', 'ACTIVE'),
  (10, 'Marketing Attribution Software', 'Track every touchpoint from click to closed deal', 'See attribution data', 'ACTIVE')
ON CONFLICT DO NOTHING;

INSERT INTO leads (id, email, name, company, industry, pain_points, status, email_opt_out, touch_count) VALUES
  (1, 'benjamin92clarke@gmail.com', 'Benjamin', 'Benjamin Legal Tech', 'Legal Technology', 'Complex document management and compliance tracking', 'NEW', FALSE, 0),
  (2, 'darrielcollins4@gmail.com', 'Collins', 'Darriel Solutions', 'Software Development', 'Scaling development processes and team coordination', 'NEW', FALSE, 0),
  (3, 'martinkam1216@gmail.com', 'Martinkam1216', 'MarTechKam Inc', 'Marketing Technology', 'Customer attribution and campaign optimization', 'NEW', FALSE, 0),
  (4, 'martinezzval12@gmail.com', 'Darriel', 'Darriel Financial', 'Financial Technology', 'SOC2 compliance for enterprise sales acceleration', 'NEW', FALSE, 0),
  (5, 'elvomanton@gmail.com', 'Elvomanton', 'Elvo Analytics', 'Data Analytics', 'Real-time dashboard automation and insights', 'NEW', FALSE, 0),
  (6, 'gabriellegarcia9090@gmail.com', 'Gabriel', 'GabrielTech Innovations', 'Technology Consulting', 'DevOps automation and deployment efficiency', 'NEW', FALSE, 0)
ON CONFLICT DO NOTHING;

INSERT INTO campaign_leads (campaign_id, lead_id, emails_sent) VALUES
  (1,1,0), (1,2,0), (1,3,0), (1,4,0), (1,5,0), (1,6,0)
ON CONFLICT DO NOTHING;

INSERT INTO staff (id, name, email, timezone, availability, dummy_slots) VALUES
  (1, 'Benjamin', 'benjamin92clarke@gmail.com', 'UTC', '{"monday": ["09:00-12:00","13:00-17:00"]}', '["2026-04-28 10:00", "2026-04-28 14:00", "2026-04-29 11:00"]'),
  (2, 'Collins', 'darrielcollins4@gmail.com', 'America/New_York', '{"tuesday": ["10:00-15:00"]}', '["2026-04-28 11:00", "2026-04-29 10:00", "2026-04-29 13:00"]'),
  (3, 'Darriel', 'martinezzval12@gmail.com', 'America/Los_Angeles', '{"wednesday": ["11:00-16:00"]}', '["2026-04-29 12:00", "2026-04-29 15:00", "2026-04-30 11:00"]'),
  (4, 'Elvomanton', 'elvomanton@gmail.com', 'America/Chicago', '{"thursday": ["09:00-12:00","13:00-17:00"]}', '["2026-04-30 10:00", "2026-04-30 14:00", "2026-05-01 09:00"]'),
  (5, 'Martinkam', 'martinkam1216@gmail.com', 'America/Los_Angeles', '{"friday": ["10:00-15:00"]}', '["2026-05-01 11:00", "2026-05-01 13:00", "2026-05-04 10:00"]'),
  (6, 'Gabriel', 'gabriellegarcia9090@gmail.com', 'America/New_York', '{"monday": ["09:00-12:00","13:00-17:00"]}', '["2026-04-28 09:00", "2026-04-28 15:00", "2026-04-29 14:00"]')
ON CONFLICT DO NOTHING;

INSERT INTO campaign_staff (campaign_id, staff_id) VALUES
  (1,1), (1,2), (1,3), (1,4), (1,5), (1,6)
ON CONFLICT DO NOTHING;

SELECT setval('campaigns_id_seq', (SELECT MAX(id) FROM campaigns));
SELECT setval('leads_id_seq', (SELECT MAX(id) FROM leads));
SELECT setval('staff_id_seq', (SELECT MAX(id) FROM staff));
