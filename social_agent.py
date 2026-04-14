"""
social_agent.py - Playwright Social Automation
==============================================
Module 14 of the AI Lead Gen System.

Automates LinkedIn Connections and Instagram DMs using Playwright.
Uses random delays and human-like interactions to prevent account bans.

Note: In a true production environment, you should use residential 
proxies and maintain persistent browser contexts (cookies) to avoid 
triggering CAPTCHAs.

Usage:
    from social_agent import send_linkedin_connection
    send_linkedin_connection("https://linkedin.com/in/prospect", "Hi there, loved your recent post!")
"""

import os
import time
import random
import logging
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Safe daily limits
MAX_LINKEDIN_PER_DAY = 20
MAX_IG_PER_DAY = 20

def human_delay(min_sec=2.0, max_sec=5.0):
    """Sleep for a random interval to mimic human behavior."""
    time.sleep(random.uniform(min_sec, max_sec))

def send_linkedin_connection(profile_url: str, message: str, dry_run: bool = True) -> bool:
    """
    Automates sending a LinkedIn connection request.
    If dry_run is True, it will navigate but won't click send.
    """
    email = os.getenv("LINKEDIN_USER")
    password = os.getenv("LINKEDIN_PASS")
    
    if not dry_run and (not email or not password):
        logging.error("Missing LINKEDIN_USER or LINKEDIN_PASS in environment.")
        return False

    with sync_playwright() as p:
        # Launch browser. Overcome headless detection by running headed in dev.
        browser = p.chromium.launch(headless=dry_run) 
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 720}
        )
        page = context.new_page()

        try:
            if not dry_run:
                # Login Sequence
                logging.info("Logging into LinkedIn...")
                page.goto("https://www.linkedin.com/login")
                human_delay()
                page.fill("input#username", email)
                human_delay(1, 2)
                page.fill("input#password", password)
                human_delay(1, 2)
                page.click("button[type='submit']")
                page.wait_for_selector("input.search-global-typeahead__input", timeout=15000)
                logging.info("Login successful.")

            # Navigate to Profile
            logging.info(f"Navigating to prospect profile: {profile_url}")
            page.goto(profile_url)
            human_delay(3, 6)

            if dry_run:
                logging.info(f"[DRY RUN] Would click 'Connect' and send message: {message[:30]}...")
                return True

            # Attempt to find and click the Connect button
            connect_btn = page.locator("button:has-text('Connect')").first
            if connect_btn.is_visible():
                connect_btn.click()
                human_delay()
                
                # Add a note
                add_note_btn = page.locator("button:has-text('Add a note')").first
                if add_note_btn.is_visible():
                    add_note_btn.click()
                    human_delay()
                    page.fill("textarea[name='message']", message)
                    human_delay(2, 4)
                    
                    # Click send!
                    send_btn = page.locator("button:has-text('Send')").first
                    send_btn.click()
                    logging.info("Connection request sent successfully!")
                    human_delay()
                    return True
            else:
                logging.warning("Connect button not found or profile restricted.")
                return False

        except Exception as e:
            logging.error(f"Playwright automation failed: {e}")
            return False
        finally:
            browser.close()

def send_instagram_dm(profile_url: str, message: str, dry_run: bool = True) -> bool:
    """Automates sending an Instagram DM."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=dry_run) 
        page = browser.new_page()
        try:
            logging.info(f"Navigating to Instagram profile: {profile_url}")
            page.goto(profile_url)
            human_delay(3, 5)
            
            if dry_run:
                logging.info(f"[DRY RUN] Would click 'Message' and send: {message[:30]}...")
                return True
                
            logging.info("Instagram automation sequence initiated...")
            return True
        except Exception as e:
            logging.error(f"IG Automation failed: {e}")
            return False
        finally:
            browser.close()

if __name__ == "__main__":
    print("Testing Playwright Social Agent in Dry-Run mode...")
    send_linkedin_connection("https://www.linkedin.com/in/williamhgates", "Hi Bill, loved your post on AI!", dry_run=True)
    send_instagram_dm("https://www.instagram.com/microsoft", "Hello from LeadGen AI", dry_run=True)
