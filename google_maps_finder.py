"""
google_maps_finder.py - Automated Lead Scraper
==============================================
Searches Google Maps for local businesses and adds them to the database.
Uses the 'googlemaps' package.
"""

import os
import logging
from dotenv import load_dotenv
from sqlite3 import IntegrityError
import googlemaps

import database

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

load_dotenv()
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")

def get_googlemaps_client():
    """Returns a connected googlemaps client or None if API key is missing."""
    if not GOOGLE_MAPS_API_KEY:
        return None
    return googlemaps.Client(key=GOOGLE_MAPS_API_KEY)

def search_local_businesses(query: str, location: str) -> int:
    """
    Searches Google Maps for businesses matching the query and location.
    Extracts their details and adds them to the prospect database.
    
    Args:
        query: e.g. "plumbers", "dentists"
        location: e.g. "Austin, TX", "London"
        
    Returns:
        Number of *new* prospects successfully added.
    """
    client = get_googlemaps_client()
    if not client:
        logging.error("GOOGLE_MAPS_API_KEY is missing from .env.")
        return 0

    search_query = f"{query} in {location}"
    logging.info(f"Searching Google Maps for: '{search_query}'")
    
    try:
        # Perform text search
        places_result = client.places(query=search_query)
        
        if not places_result.get('results'):
            logging.info("No results found.")
            return 0
            
        added_count = 0
        
        for place in places_result['results']:
            place_id = place.get('place_id')
            if not place_id:
                continue
                
            # Get Place Details to retrieve website and phone number
            details_response = client.place(
                place_id, 
                fields=['name', 'formatted_address', 'formatted_phone_number', 'website']
            )
            details = details_response.get('result', {})
            
            name = details.get('name', place.get('name', 'Unknown'))
            address = details.get('formatted_address', place.get('formatted_address', ''))
            phone = details.get('formatted_phone_number', '')
            website = details.get('website', '')
            
            # Prevent duplicates by checking if company name already exists
            existing_match = database.search_by_company(name)
            is_duplicate = any(e['company'].lower() == name.lower() for e in existing_match)
            if is_duplicate:
                logging.debug(f"Skipping duplicate prospect: {name}")
                continue
            
            try:
                # Add to DB. Maps doesn't list individual owners easily, so we use a placeholder role.
                database.add_prospect(
                    name="Owner/Manager", 
                    company=name,
                    phone=phone,
                    website=website,
                    notes=f"Address: {address}",
                    status="new",
                    lead_score=50
                )
                added_count += 1
                logging.info(f"Added new prospect: {name} ({phone})")
                
            except IntegrityError:
                logging.debug(f"Skipped duplicate or invalid prospect: {name}")

        logging.info(f"Successfully added {added_count} new leads to the database.")
        return added_count
        
    except Exception as e:
        logging.error(f"Error while searching Google Maps: {str(e)}")
        return 0

def find_and_add_prospects(query: str, location: str, limit: int = 3) -> list:
    """
    Search Google Maps for businesses, add new ones to the DB, and return their
    prospect dicts (with DB IDs). Only returns businesses that have a website,
    since the research pipeline needs one.

    Args:
        query:    e.g. "dentists", "gyms", "accountants"
        location: e.g. "Manchester", "Austin TX"
        limit:    Maximum number of results to return (default 3).

    Returns:
        List of prospect dicts as stored in the DB (id, company, website, …).
    """
    client = get_googlemaps_client()
    if not client:
        logging.error("GOOGLE_MAPS_API_KEY is missing from .env.")
        return []

    search_query = f"{query} in {location}"
    logging.info(f"[find_and_add_prospects] Searching: '{search_query}'")

    try:
        places_result = client.places(query=search_query)
        if not places_result.get("results"):
            logging.info("[find_and_add_prospects] No results returned.")
            return []

        added = []

        for place in places_result["results"]:
            if len(added) >= limit:
                break

            place_id = place.get("place_id")
            if not place_id:
                continue

            details = client.place(
                place_id,
                fields=["name", "formatted_address", "formatted_phone_number", "website"],
            ).get("result", {})

            name    = details.get("name") or place.get("name") or "Unknown"
            address = details.get("formatted_address") or place.get("formatted_address") or ""
            phone   = details.get("formatted_phone_number") or ""
            website = details.get("website") or ""

            if not website:
                logging.debug(f"  Skipping '{name}' — no website.")
                continue

            # Find or create in DB
            existing = database.search_by_company(name)
            matched  = [p for p in existing if p.get("company", "").lower() == name.lower()]
            if matched:
                prospect_id = matched[0]["id"]
                logging.debug(f"  '{name}' already in DB (id={prospect_id}).")
            else:
                try:
                    prospect_id = database.add_prospect(
                        name="Owner/Manager",
                        company=name,
                        phone=phone,
                        website=website,
                        notes=f"Address: {address}",
                        status="qualified",
                        lead_score=55,
                    )
                    logging.info(f"  Added '{name}' to DB (id={prospect_id}).")
                except IntegrityError:
                    existing = database.search_by_company(name)
                    if existing:
                        prospect_id = existing[0]["id"]
                    else:
                        continue

            prospect = next(
                (p for p in database.get_all_prospects() if p["id"] == prospect_id),
                None,
            )
            if prospect:
                added.append(dict(prospect))

        logging.info(f"[find_and_add_prospects] Returning {len(added)} prospects.")
        return added

    except Exception as exc:
        logging.error(f"[find_and_add_prospects] Error: {exc}")
        return []


if __name__ == "__main__":
    print("Testing map scraper config...")
    if GOOGLE_MAPS_API_KEY:
        print("API Key present. Setup complete.")
    else:
        print("Missing GOOGLE_MAPS_API_KEY in .env.")
