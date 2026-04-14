from outreach import generate_email

prospects = [
    {
        "name": "Sarah Chen",
        "company": "Acme SaaS",
        "niche": "CRM automation for mid-market agencies",
        "website_headline": "The CRM built for fast-moving agencies",
        "competitors": "HubSpot, Pipedrive",
        "ad_status": "running_ads",
    },
    {
        "name": "Marcus Rivera",
        "company": "BluePeak Ventures",
        "niche": "B2B SaaS growth consulting",
        "hiring_signal": "hiring an SDR on LinkedIn",
    },
    {
        "name": "Elena Kovacs",
        "company": "Drift Analytics",
        "niche": "no-code analytics platform for ops teams",
        "product_feature": "native integration with Snowflake and dbt",
        "outbound_status": "no_outbound",
    },
    {
        "name": "Priya Nair",
        "company": "Nexus Health",
        "niche": "health-tech SaaS for clinic administrators",
        "linkedin_activity": "reducing admin burnout in NHS clinics",
    },
    {
        "name": "David Osei",
        "company": "Fortis Logistics",
        "outbound_status": "no_outbound",
    },
]

for i, p in enumerate(prospects, 1):
    result = generate_email(p)
    sep = "=" * 60
    print(sep)
    print(f"EMAIL {i}: {p['name']} / {p['company']}")
    print(sep)
    print(f"Subject: {result['subject']}")
    print()
    print(result["body"])
    print()
