PRAGMA foreign_keys = ON;

-- Sample campaigns with diverse topics
INSERT OR IGNORE INTO campaigns (id, name, value_proposition, cta, status) VALUES
  (1, 'Outbound Outreach - Q2', 'Increase pipeline with our AI sales assistant', 'Book a quick demo', 'ACTIVE'),
  (2, 'Re-engagement', 'We have new features you might like', 'Learn more', 'PAUSED'),
  (3, 'SOC2 Compliance Fast-Track', 'Skip months of SOC2 compliance work with our automated solution', 'Get SOC2 ready in weeks', 'ACTIVE'),
  (4, 'DevOps Automation Revolution', 'Cut deployment time by 80% with AI-powered DevOps automation', 'See the demo', 'ACTIVE'),
  (5, 'Cybersecurity Risk Assessment', 'Identify security vulnerabilities before attackers do', 'Start free security scan', 'ACTIVE'),
  (6, 'Sales Pipeline Optimization', 'Double your qualified leads with predictive lead scoring', 'Boost your pipeline', 'ACTIVE'),
  (7, 'Customer Success Automation', 'Reduce churn by 40% with proactive customer health monitoring', 'Improve retention now', 'ACTIVE'),
  (8, 'Financial Analytics Dashboard', 'Make data-driven decisions with real-time financial insights', 'View live dashboard', 'ACTIVE'),
  (9, 'HR Onboarding Streamline', 'Onboard new hires 3x faster with automated workflows', 'Streamline onboarding', 'ACTIVE'),
  (10, 'Marketing Attribution Software', 'Track every touchpoint from click to closed deal', 'See attribution data', 'ACTIVE');

-- Sample leads
INSERT OR IGNORE INTO leads (id, email, name, company, industry, pain_points, status, email_opt_out, touch_count) VALUES
  (1, 'lawstands@gmail.com', 'Lawstands', 'LawStands Legal Tech', 'Legal Technology', 'Complex document management and compliance tracking', 'NEW', 0, 0),
  (2, 'konnect1795@gmail.com', 'Konnect1795', 'Konnect Solutions', 'Software Development', 'Scaling development processes and team coordination', 'NEW', 0, 0),
  (3, 'martinkam1216@gmail.com', 'Martinkam1216', 'MarTechKam Inc', 'Marketing Technology', 'Customer attribution and campaign optimization', 'NEW', 0, 0),
  (4, 'obogomaty@gmail.com', 'Obogomaty', 'Obogo Financial', 'Financial Technology', 'SOC2 compliance for enterprise sales acceleration', 'NEW', 0, 0),
  (5, 'mayowasolomon@gmail.com', 'Mayowasolomon', 'Solomon Analytics', 'Data Analytics', 'Real-time dashboard automation and insights', 'NEW', 0, 0),
  (6, 'nurudeenh@gmail.com', 'Nurudeenh', 'NurusTech Innovations', 'Technology Consulting', 'DevOps automation and deployment efficiency', 'NEW', 0, 0);

-- Link leads to campaign 1
INSERT OR IGNORE INTO campaign_leads (campaign_id, lead_id, emails_sent) VALUES
  (1,1,0),
  (1,2,1),
  (1,3,0),
  (1,4,0),
  (1,5,0),
  (1,6,0);

-- Sample staff
INSERT OR IGNORE INTO staff (id, name, email, timezone, availability) VALUES
  (1, 'Nurudeen', 'nurudeenh@gmail.com', 'UTC', '{"monday": ["09:00-12:00","13:00-17:00"]}'),
  (2, 'Mustapha', 'konnect1795@gmail.com', 'America/New_York', '{"tuesday": ["10:00-15:00"]}'),
  (3, 'Mayowa', 'mayowasolomon@gmail.com', 'America/Los_Angeles', '{"wednesday": ["11:00-16:00"]}'),
  (4, 'Obogomaty', 'obogomaty@gmail.com', 'America/Chicago', '{"thursday": ["09:00-12:00","13:00-17:00"]}'),
  (5, 'Martinkam', 'martinkam1216@gmail.com', 'America/Los_Angeles', '{"friday": ["10:00-15:00"]}'),
  (6, 'Lawstands', 'lawstands@gmail.com', 'America/New_York', '{"monday": ["09:00-12:00","13:00-17:00"]}');
