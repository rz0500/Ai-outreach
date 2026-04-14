"""
main.py - Lead Generation Pipeline Orchestrator
===============================================
The master entry point for the system. Runs the entire pipeline:
1. Checks for replies to pause active sequences
2. Scrapes Google Maps for fresh leads
3. Scores raw leads
4. Promotes qualified leads into the active sequence
5. Runs the sequencer to send follow-up emails
6. Generates a daily report summary

Usage:
    python main.py --query "dentists" --location "London"
    python main.py --live  # DANGER: Will actually send emails
"""

import argparse
import logging

import database
import inbox_monitor
import google_maps_finder
import scorer
import research_agent
import reporter
from database import ensure_sequence_enrollment
from sequence_dispatcher import run_multichannel_sequence

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def run_pipeline(query: str, location: str, dry_run: bool = True):
    print("=" * 60)
    print(f"STARTING LEAD GENERATION PIPELINE - {'DRY RUN' if dry_run else 'LIVE'}")
    print("=" * 60)
    
    # ---------------------------------------------------------
    # 1. Initialize Database Tables
    # ---------------------------------------------------------
    database.initialize_database()
    database.initialize_outreach_table()
    
    # ---------------------------------------------------------
    # 2. Check Inbox for replies -> Pause active sequences
    # ---------------------------------------------------------
    print("\n[Stage 1] Checking Inbox for Replies...")
    # Pass mark_as_read=not dry_run to prevent messing with real emails during local testing
    replies = inbox_monitor.check_for_replies(mark_as_read=not dry_run)
    print(f"Processed {replies} new replies.")
    
    # ---------------------------------------------------------
    # 3. Find New Leads via Maps Scraper
    # ---------------------------------------------------------
    print(f"\n[Stage 2] Scraping Google Maps for '{query} in {location}'...")
    if dry_run:
        print("  (Running in dry_run mode, but scraper will still execute if API key is present)")
    new_leads_added = google_maps_finder.search_local_businesses(query, location)
    
    # ---------------------------------------------------------
    # 4. Score New Leads
    # ---------------------------------------------------------
    print("\n[Stage 3] Scoring New Leads...")
    scorer.score_all_new()
    
    # ---------------------------------------------------------
    # 5. Move high-scoring "new" leads to "in_sequence"
    # ---------------------------------------------------------
    print("\n[Stage 4] Promoting qualified leads into the 'in_sequence' funnel...")
    all_prospects = database.get_all_prospects()
    promoted = 0
    for p in all_prospects:
        if p['status'] == 'new' and p['lead_score'] >= 40: # If Warm or Hot
            if not dry_run:
                # We move them to 'qualified' first so the Research Agent can process them
                database.update_status(p['id'], 'qualified')
            promoted += 1
            
    action = "Would promote" if dry_run else "Promoted"
    print(f"  {action} {promoted} leads (Score >= 40) to 'qualified' status.")
    
    # ---------------------------------------------------------
    # 6. Deep Research Agent
    # ---------------------------------------------------------
    print("\n[Stage 5] Executing Deep Research Crawler on 'qualified' leads...")
    if dry_run:
        print("  (Running in dry_run mode, skipping web crawls and Anthropic API calls)")
    else:
        researched = research_agent.run_research_batch()
        print(f"  Successfully researched and generated hooks for {researched} prospects.")
        # After research, move them fully into sequence
        for p in database.get_all_prospects():
            if p['status'] == 'qualified' and "[Research Hook]" in str(p.get("notes")):
                database.update_status(p['id'], 'in_sequence')
                ensure_sequence_enrollment(p['id'])
    
    # ---------------------------------------------------------
    # 7. Run the Auto-Sequencer (Sends Emails)
    # ---------------------------------------------------------
    print("\n[Stage 6] Executing the Outreach Sequencer...")
    run_multichannel_sequence(dry_run=dry_run)
    
    # ---------------------------------------------------------
    # 8. Generate Daily Report
    # ---------------------------------------------------------
    print("\n[Stage 7] Generating Final Pipeline Report...\n")
    reporter.print_report()
    
    print("\n" + "=" * 60)
    print("PIPELINE EXECUTION COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Lead Gen Master Orchestrator")
    parser.add_argument("--query", type=str, default="plumbers", help="Business type to search for")
    parser.add_argument("--location", type=str, default="Austin, TX", help="Location to search in")
    parser.add_argument("--live", action="store_true", help="Run in LIVE mode (WILL SEND REAL EMAILS & UPDATE DB)")
    
    args = parser.parse_args()
    
    # Run the orchestrator
    run_pipeline(args.query, args.location, dry_run=not args.live)
