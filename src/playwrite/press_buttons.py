from playwright.sync_api import sync_playwright
import time

def automate_purchase_flow():
    # --- CONFIGURATION ---
    # 1. Replace this with the actual URL you want to open
    TARGET_URL = "https://www.eventbrite.nl/e/assembly-in-motion-filmmakers-creatives-sip-socialize-tickets-1906813553669?aff=ehometext" # Placeholder: Change this!

    # 2. Selectors for the buttons.
    # We use a text-based selector which is usually reliable.
    # The script looks for a button that contains the text 'Accept' or 'Accept Cookies'.
    COOKIE_BUTTON_SELECTOR = 'button:has-text("Accept")'

    # The script looks for a button that contains the text 'Buy Tickets', 'Tickets', OR 'reserve a seat'.
    # TICKET_BUTTON_SELECTOR = 'text=/Buy Tickets|Tickets|reserve a seat|Reserve a spot/i' # Case-insensitive regex for flexibility
    TICKET_BUTTON_SELECTOR = 'button:has-text("Buy Tickets"), button:has-text("Tickets"), button:has-text("Reserve a seat"), button:has-text("Reserve a spot")'
    # REGISTER_BUTTON_SELECTOR = 'button:has-text("Register")'
    REGISTER_BUTTON_SELECTOR = "button:has-text('/Register|Sign Up|Join Now|Enroll/i')"

    # 3. Time delay to make actions visible and allow the page to load
    ACTION_DELAY_SECONDS = 2
    # ---------------------

    print(f"Starting automation for URL: {TARGET_URL}")

    # Use sync_playwright to manage the browser context
    with sync_playwright() as p:
        # Launch the browser (using Chromium for reliable execution)
        # Set headless=False to watch the actions in real-time
        # browser = p.chromium.launch(headless=True)
        browser = p.chromium.launch(headless=False, slow_mo=200)
        page = browser.new_page()

        try:
            # 1. Open the target link
            print(f"Navigating to {TARGET_URL}...")
            page.goto(TARGET_URL)
            page.set_viewport_size({"width": 1280, "height": 800})
            time.sleep(ACTION_DELAY_SECONDS)

            # 2. Press the "Accept Cookies" button
            try:
                print(f"Attempting to click Cookie button using selector: '{COOKIE_BUTTON_SELECTOR}'")
                
                # Clicks the first element matching the selector, waiting up to 5 seconds
                page.click(COOKIE_BUTTON_SELECTOR, timeout=5000)
                print("✅ Successfully clicked 'Accept Cookies' button.")
                time.sleep(ACTION_DELAY_SECONDS)
            except Exception:
                print("⚠️ Cookie button not found or already accepted (or element timeout). Skipping step.")
                # This is common; sometimes the banner loads slowly or is already gone.

            # 3. Press the "Buy Tickets" button
            try:
                print(f"Attempting to click Ticket button using selector: '{TICKET_BUTTON_SELECTOR}'")
                
                # Clicks the element, waiting up to 10 seconds (gives page more time to load)
                page.click(TICKET_BUTTON_SELECTOR, timeout=5000)
                print("✅ Successfully clicked 'Buy Tickets' or 'Reserve a Seat' button.")
                time.sleep(ACTION_DELAY_SECONDS)
            except Exception as e:
                print(f"❌ Failed to click 'Buy Tickets' button.")
                print(f"Error details: {e}")

            # print("🔍 After clicking Buy Tickets, checking page structure...")

            # for f in page.frames:
            #     print("Frame URL:", f.url)
            #     try:
            #         buttons = f.locator("button")
            #         count = buttons.count()
            #         print(f"  Found {count} buttons.")
            #         for i in range(min(count, 5)):
            #             print("   -", buttons.nth(i).inner_text())
            #     except Exception:
            #         print("   (Cannot inspect this frame)")

            #     # 4. Press the "Register" button
            #     # 4. Try to find the Register/Checkout button anywhere (even in modals)
            # try:
            #     print("⏳ Waiting for Eventbrite modal and Register button to appear...")

            #     # Wait for the modal container to appear
            #     page.wait_for_selector('[data-spec="eds-modal"]', state="visible", timeout=30000)
            #     print("✅ Modal detected.")

            #     # Now wait specifically for the button inside it
            #     REGISTER_BUTTON_SELECTOR = (
            #         'button[data-spec="eds-modal__primary-button"], '
            #         'button[data-testid="eds-modal__primary-button"], '
            #         'button:has-text("Register")'
            #     )

            #     page.wait_for_selector(REGISTER_BUTTON_SELECTOR, state="visible", timeout=15000)
            #     print("🎯 Register button found — attempting to click...")

            #     # Use locator() for reliability
            #     button = page.locator(REGISTER_BUTTON_SELECTOR).first
            #     button.scroll_into_view_if_needed()
            #     button.click(force=True)
            #     print("✅ Successfully clicked the Register button in modal.")
            #     time.sleep(ACTION_DELAY_SECONDS)

            # except Exception as e:
            #     print(f"❌ Failed to click 'Register' button.")
            #     print(f"Error details: {e}")

            #     print("🔍 Dumping visible buttons for debugging:")
            #     all_buttons = page.locator("button")
            #     count = all_buttons.count()
            #     for i in range(min(count, 20)):
            #         try:
            #             txt = all_buttons.nth(i).inner_text()
            #             print(f"  {i+1:02d}: {txt}")
            #         except:
            #             pass

            
            # try:
            #     print(f"Attempting to click Register button using selector: '{REGISTER_BUTTON_SELECTOR}'")
                
            #     # Clicks the element, waiting up to 10 seconds
            #     page.click(REGISTER_BUTTON_SELECTOR, timeout=10000)
            #     print("✅ Successfully clicked 'Register' button.")
            #     time.sleep(ACTION_DELAY_SECONDS)
            # except Exception as e:
            #     print(f"❌ Failed to click 'Register' button.")
            #     print(f"Error details: {e}")
        except Exception as e:
            print(f"An error occurred during navigation or browser operation: {e}")

        finally:
            print("Automation finished. Closing browser in 5 seconds...")
            time.sleep(60*5)
            browser.close()

if __name__ == "__main__":
    automate_purchase_flow()