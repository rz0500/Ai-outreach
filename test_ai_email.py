from ai_engine import generate_hyper_personalized_email
import json

prospect = {
    "name": "Sarah Chen",
    "company": "Acme SaaS",
    "niche": "CRM automation for mid-market agencies",
    "website_headline": "The CRM built for fast-moving agencies",
    "competitors": "HubSpot, Pipedrive",
    "outbound_status": "no_outbound",
    "product_feature": "native AI workflow builder",
    "notes": "Pain Point: Agencies spend 15h a week managing scattered lead data.\nGrowth Signal: Just launched a new reporting dashboard."
}

print("Running AI Engine...")
try:
    result = generate_hyper_personalized_email(prospect)
    print("\n--- AI GENERATED EMAIL ---")
    print(f"SUBJECT: {result['subject']}\n")
    print(result['body'])
    print(f"\n[Quality Score: {result['quality_score']}/100]")
    if result["warnings"]:
        print(f"[Warnings: {result['warnings']}]")
except Exception as e:
    print(f"\nAI Engine Error: {e}")
    print("\n(Note: If this is an AuthenticationError, your .env file needs a valid ANTHROPIC_API_KEY)")
