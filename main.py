from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from imapclient import IMAPClient
import pyzmail
import re
import time
from pynput.keyboard import Listener, Key, KeyCode
import threading
import os
import csv


def load_patients_from_csv(csv_path):
    patients = []
    with open(csv_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            # Skip completely empty rows
            if not any(row.values()):
                continue
            patient = { (k or '').strip(): (v or '').strip() for k, v in row.items() if k }
            patients.append(patient)
    return patients

def take_screenshot(page, filename):
    os.makedirs('screenshots', exist_ok=True)  # Ensure folder exists
    full_path = os.path.join('screenshots', filename)
    page.screenshot(path=full_path)
    print(f"Screenshot saved: {full_path}")
    return full_path


# =============================================
# 1. OTP Retrieval Function
# =============================================

def get_latest_otp_ionos(email, password, retries=5, wait_sec=5):
    server = 'imap.ionos.com'
    with IMAPClient(host=server, ssl=True) as client:
        client.login(email, password)
        client.select_folder('INBOX')
        for attempt in range(retries):
            print(f"Checking for OTP email (Attempt {attempt + 1}/{retries})...")
            messages = client.search(['UNSEEN'])
            for uid in reversed(messages):
                raw_message = client.fetch([uid], ['BODY[]', 'FLAGS'])
                message = pyzmail.PyzMessage.factory(raw_message[uid][b'BODY[]'])
                if message.text_part:
                    body = message.text_part.get_payload().decode(message.text_part.charset)
                elif message.html_part:
                    body = message.html_part.get_payload().decode(message.html_part.charset)
                else:
                    continue
                otp_match = re.search(r'\b\d{6}\b', body)
                if otp_match:
                    print(f"OTP found: {otp_match.group(0)}")
                    return otp_match.group(0)
            time.sleep(wait_sec)
    print("OTP not found in email.")
    return None


# =============================================
# 2. Form Data Configuration
# =============================================

form_data = {
    "user_id": "mca@hiisight.com",
    "password": "May@2025",
    "email_address": "code@hiisight.com",
    "email_password": "Ravi@1443101",
    "patients": load_patients_from_csv("patients.csv")
}

# =============================================
# Address Map by Provider Type Code (Numeric)
# =============================================
ADDRESS_MAP = {
    "1": {  # Cardiology                              ##### mkc
        "address": "1331 W TEXAS PKWY N STE 420",
        "city": "MAY",
        "zip": "12345",
        "state": "TX"
    },
    "2": {  # Radiology                               ###### mca
        "address": "915 TEXAS RD STE 4520",
        "city": "MAY",
        "zip": "23423",
        "state": "TX"
    },
    "3": {  # Orthopedics                          ######### cls
        "address": "905 W MEDICAL CENTER BLVD STE 102",
        "city": "MAY",
        "zip": "14235",
        "state": "TX"
    }
    
}

# =========================================
# 3. Main Login Automation Function
# =========================================

def run_login():
    stop_event = threading.Event()
    diag_error_occurred = False  # Initialize the flag to avoid UnboundLocalError

    # ================================
    # 3.1 Keyboard Listener for Exit Key
    # ================================
    def on_press(key):
        if key == KeyCode.from_char('='):
            print("Exit key (=) pressed. Closing browser...")
            stop_event.set()
            return False

    # ================================
    # 3.2 Browser Initialization
    # ================================
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--start-maximized"])
        context = browser.new_context(accept_downloads=True)
        context = browser.new_context(no_viewport=True)
        page = context.new_page()

        # ================================
        # 3.3 Scroll Utility Function
        # ================================
        def inject_scroll_center():
            try:
                page.evaluate("""
                    () => {
                        window.scrollTo({ top: document.body.scrollHeight / 2 - window.innerHeight / 2, behavior: 'smooth' });
                        document.body.style.overflow = 'auto';
                    }
                """)
            except Exception as e:
                print(f"Scroll injection failed: {e}")

        # =============================================
        # 4. Login Flow
        # =============================================
        page.goto("https://www.providerportal.com/ ", wait_until="domcontentloaded")
        page.wait_for_selector('#asPrimary_ctl00_txtLoginId', timeout=30000)
        inject_scroll_center()
        page.fill('#asPrimary_ctl00_txtLoginId', form_data["user_id"])
        page.click('#asPrimary_ctl00_btnLookup')
        page.wait_for_selector('input.button.button-primary[value="Next"]', timeout=15000)
        inject_scroll_center()
        page.click('input.button.button-primary[value="Next"]')
        page.wait_for_selector('#input60', timeout=15000)
        inject_scroll_center()
        page.fill('#input60', form_data["password"])
        page.click('input.button.button-primary[value="Login"]')
        page.wait_for_selector('input.button.button-primary[value="Send Email"]', timeout=15000)
        inject_scroll_center()
        page.click('input.button.button-primary[value="Send Email"]')

        # =============================================
        # 5. OTP Handling Logic
        # =============================================
        max_attempts = 3
        attempt = 0
        otp_verified = False
        while attempt < max_attempts and not otp_verified:
            print("Waiting for OTP email...")
            page.wait_for_timeout(10000)
            otp = get_latest_otp_ionos(form_data["email_address"], form_data["email_password"])
            if not otp:
                print("Could not retrieve OTP. Exiting.")
                context.close()
                browser.close()
                return
            print(f"Attempting to enter OTP: {otp}")
            page.wait_for_selector('#input103', timeout=15000)
            inject_scroll_center()
            page.fill('#input103', otp)
            page.click('input.button.button-primary[value="Verify Code"]')
            try:
                print("Checking if OTP verification was successful...")
                page.wait_for_selector('#asPrimary_ctl00_cmdAgreeContinue', timeout=15000)
                print("OTP Verified. Redirected to the next page.")
                otp_verified = True
            except PlaywrightTimeoutError:
                attempt += 1
                print(f"OTP verification failed. Attempt {attempt}/{max_attempts}. Retrying...")
                if attempt >= max_attempts:
                    print("Max OTP attempts reached. Exiting.")
                    context.close()
                    browser.close()
                    return
                print("Restarting OTP process...")
                page.click("a.resend-link")
                page.wait_for_timeout(5000)

        if not otp_verified:
            print("OTP verification failed after multiple attempts. Exiting.")
            context.close()
            browser.close()
            return

        # =============================================
        # 6. Post-Login Navigation
        # =============================================
        page.wait_for_timeout(7000)
        page.wait_for_selector('#asPrimary_ctl00_cmdAgreeContinue', timeout=15000)
        inject_scroll_center()
        page.click('#asPrimary_ctl00_cmdAgreeContinue')
        page.wait_for_timeout(7000)

        # =============================================
        # 7. Patient Processing Loop
        # =============================================
        for i, patient in enumerate(form_data["patients"]):
            print(f"Processing patient {i + 1}/{len(form_data['patients'])}...")

            retry_attempt = 0
            max_retries = 2  # Try selecting 1st and 2nd member search result max

            while retry_attempt < max_retries:
                try:
                    # -------------------------
                    # 7.1 Fill Patient Info
                    # -------------------------
                    page.fill('#asPrimary_ctl00_txtDateOfService', patient['date_of_service'])
                    time.sleep(1)
                    page.fill('#asPrimary_ctl00_TxbFirstName', patient['first_name'])
                    time.sleep(1)
                    page.fill('#asPrimary_ctl00_TxbLastName', patient['last_name'])
                    time.sleep(1)
                    page.fill('#asPrimary_ctl00_TxbMemberNumber', patient['member_id'])
                    time.sleep(1)
                    page.fill('#asPrimary_ctl00_TxbDateOfBirth', patient['dob'])
                    time.sleep(1)
                    inject_scroll_center()

                    # -------------------------
                    # 7.4 Try Diagnostic Imaging immediately after filling patient info
                    # -------------------------
                    diag_card = page.locator('div[data-contact-display="Phone"] h3.card-title', has_text="Diagnostic Imaging")
                    if diag_card.is_visible(timeout=5000):
                        diag_card.click()
                        print("Diagnostic Imaging clicked.")
                        time.sleep(3)

                        print("Proceeding without successful member selection.")
                        break  # Exit retry loop and proceed to next patient

                    else:
                        print("Diagnostic Imaging not found. Proceeding with member search logic.")

                    # Flag to track if we successfully did member search/selection
                    member_selected = False

                    # -------------------------
                    # 7.2 Member Search (Optional)
                    # -------------------------
                    page.click('#asPrimary_ctl00_BtnSearch', no_wait_after=True)
                    try:
                        page.wait_for_selector('#asPrimary_ctl00_gvSearchMembers_ctl02_cmdSelectMember', timeout=15000)
                        print("Member search results loaded.")

                        # -------------------------
                        # 7.3 Try to select member
                        # -------------------------
                        row_index = retry_attempt + 2  # ctl02 for 1st, ctl03 for 2nd
                        select_member_id = f'#asPrimary_ctl00_gvSearchMembers_ctl0{row_index}_cmdSelectMember'
                        patient_link = page.locator(select_member_id)

                        if patient_link.is_visible(timeout=5000):
                            patient_link.click()
                            print(f"Selected member at row {row_index}.")
                            time.sleep(5)
                            member_selected = True
                        else:
                            print(f"No member link found at row {row_index}.")
                    except PlaywrightTimeoutError:
                        print("Member search timed out — skipping to Diagnostic Imaging.")
                        # No need to break; continue to diagnostic imaging

                    # -------------------------
                    # 7.4 Try Diagnostic Imaging (after member search)
                    # -------------------------
                    diag_card = page.locator('div[data-contact-display="Phone"] h3.card-title', has_text="Diagnostic Imaging")
                    if diag_card.is_visible(timeout=5000):
                        diag_card.click()
                        print("Diagnostic Imaging clicked.")
                        time.sleep(3)

                        if not member_selected:
                            print("Proceeding without successful member selection.")

                        break  # Exit retry loop and proceed
                    else:
                        print("Diagnostic Imaging not found.")

                    # -------------------------
                    # 7.5 Failed attempt - Take screenshot, Go Home, and retry
                    # -------------------------
                    take_screenshot(page, f"diag_error_{patient['first_name']}_{patient['last_name']}_try{retry_attempt+1}.png")

                    home_button = page.locator('#asNavigation_ctl00_hlHome')
                    if home_button.is_visible(timeout=5000):
                        home_button.click()
                        page.wait_for_timeout(5000)
                        print("Returned to Home screen.")
                    else:
                        print("Failed to return to Home screen.")

                    retry_attempt += 1

                except Exception as e:
                    print(f"Error during patient retry {retry_attempt + 1}: {e}")
                    retry_attempt += 1
                    continue

            if retry_attempt == max_retries:
                print(f"Skipping patient {patient['first_name']} {patient['last_name']} after {max_retries} failed attempts.")
                continue


            # -------------------------
            # 7.4 Phone Entry
            # -------------------------
            try:
                phone_input = page.locator("#txbPhone")
                if phone_input.is_visible(timeout=5000):
                    page.fill('#txbPhone', patient['phone'])
                    page.select_option('#ddlPhoneType', value=patient['phone_type'])
                    print("Phone and type filled.")
                else:
                    print("Phone fields not found. Skipping...")
            except Exception:
                print("Phone fields not found or timed out. Skipping phone entry.")
            time.sleep(2)

            # -------------------------
            # 7.5 Start Order Request
            # -------------------------
            try:
                page.wait_for_selector('#cmdContinue', timeout=15000)
                page.click('#cmdContinue')
                print("Start Order Request clicked.")
            except Exception as e:
                print(f"Failed to click Start Order Request button: {e}")
            time.sleep(5)

            # -------------------------
            # 7.6 Next Button
            # -------------------------
            try:
                next_button = page.locator('#asPrimary_ctl00_cmdNext')
                if next_button.is_visible(timeout=15000):
                    next_button.click()
                    print("Next button clicked.")
                else:
                    print("⏩ Next button not visible — skipping to address step.")
            except Exception as e:
                print(f"Failed to click Next button: {e}")
            time.sleep(5)

            # -------------------------
            # 7.7 Address Search
            # -------------------------
            try:
                provider_code = str(patient.get('provider_type', '')).strip()
                provider_code = re.sub(r'\D', '', provider_code)  # only digits
                address_info = ADDRESS_MAP.get(provider_code)

                print(f"Looking up address for provider_type: '{provider_code}'")
                
                if not address_info:
                    print(f"⚠️ Unknown provider_type '{provider_code}' for patient {patient['first_name']} {patient['last_name']}. Skipping address search.")
                else:
                    page.check('#asSearch_ctl00_rbSearchType_2')
                    page.fill('#asSearch_ctl00_tbAddress', address_info['address'])
                    page.fill('#asSearch_ctl00_tbCity', address_info['city'])
                    state = address_info['state']
                    page.select_option('#asSearch_ctl00_ddlState', state)
                    print(f"🌐 State selected: {state}") 
                    page.fill('#asSearch_ctl00_tbZip', address_info['zip'])
                    page.click('#asSearch_ctl00_btnSearch')
                    print(f"✅ Address search submitted for provider type code: {provider_code}")
            except Exception as e:
                print(f"❌ Failed in address search step: {e}")
            time.sleep(7)

            # -------------------------
            # 7.8 Set Page Size
            # -------------------------
            try:
                page.wait_for_selector('#asPrimary_ctl00_gvRecentProviders_ddlPageSizeList', timeout=10000)
                page.select_option('#asPrimary_ctl00_gvRecentProviders_ddlPageSizeList', '50')
                print("Page size set to 50.")
                time.sleep(5)
            except PlaywrightTimeoutError:
                print("Page size dropdown not found. Skipping selection.")

            # -------------------------
            # 7.9 Provider Finder Function
            # -------------------------
            def find_provider_across_pages():
                # Try to find provider on current page
                try:
                    locator = page.locator("a", has_text=re.compile(re.escape(patient['provider_name']), re.IGNORECASE))
                    if locator.count() > 0:
                        locator.first.click()
                        print(f"Provider {patient['provider_name']} selected.")
                        return True
                    else:
                        print(f"Provider {patient['provider_name']} not found on current page. Trying pagination...")
                except Exception as e:
                    print(f"Error locating provider on current page: {e}")

                # Try navigating through pages
                for page_number in range(1, 6):  # Try up to 5 pages
                    try:
                        next_button = page.get_by_role("link", name=">", exact=True)
                        if not next_button.is_visible():
                            print("No more pages available.")
                            break
                        next_button.click()
                        page.wait_for_timeout(5000)
                        print(f"Moved to page {page_number + 1}.")
                        locator = page.locator("a", has_text=re.compile(re.escape(patient['provider_name']), re.IGNORECASE))
                        if locator.count() > 0:
                            locator.first.click()
                            print(f"Provider {patient['provider_name']} found on page {page_number + 1}.")
                            return True
                    except Exception as e:
                        print(f"Error navigating or searching on page {page_number + 1}: {e}")
                        break
                print(f"Provider {patient['provider_name']} not found across all pages.")
                return False

            provider_found = find_provider_across_pages()
            if not provider_found:
                print(f"Provider {patient['provider_name']} was not found after loading 50 providers.")

            # -------------------------
            # 7.10 Fax Entry & Save
            # -------------------------
            if provider_found:
                try:
                    fax_input = page.locator('#asPrimary_ctl00_txbFax')
                    fax_number = '8324784570'
                    fax_input.fill('')
                    for digit in fax_number:
                        fax_input.type(digit)
                        time.sleep(0.2)
                    fax_input.focus()
                    page.keyboard.press("Tab")
                    print("Fax number entered with delay.")
                    save_btn = page.locator('#save')
                    if save_btn.is_enabled():
                        save_btn.click()
                        print("Save button clicked successfully.")
                except Exception as e:
                    print(f"Error during Save step: {e}")
            else:
                print(f"Provider {patient['provider_name']} not found.")
            time.sleep(7)

            # -------------------------
            # 7.11 CPT Code Entry
            # -------------------------
            try:
                cpt_code = patient.get("cpt_code", "")
                if cpt_code:
                    print(f"Entering CPT Code: {cpt_code}")
                    page.fill('#examSelection\\.cptCode__formControl', cpt_code)
                    page.click('svg.cl-search-icon')
                    page.wait_for_timeout(2000)
                    page.click('#addExam\\(\\)__button')
                    print("Add Exam button clicked.")
            except Exception as e:
                print(f"Error during CPT code or Add Exam steps: {e}")
            time.sleep(7)

            # -------------------------
            # 7.12 Post-Add Exam Next
            # -------------------------
            try:
                next_button = page.locator('button#applyPostClaimsForm__next\\(\\)__button')
                next_button.wait_for(timeout=10000)
                if next_button.is_visible():
                    next_button.click()
                    print("Clicked 'Next' button after Add Exam.")
                    page.wait_for_timeout(7000)
                else:
                    print("Next button not visible after Add Exam.")
            except PlaywrightTimeoutError:
                print("Timed out waiting for Next button after Add Exam.")
            except Exception as e:
                print(f"Unexpected error clicking Next after Add Exam: {e}")

            # -------------------------
            # 7.13 Diagnosis Code Entry
            # -------------------------
            try:
                diagnosis_code = patient.get("diagnosis_code", "")
                print(f"Entering diagnosis code: {diagnosis_code}")
                page.wait_for_selector('#term__formControl', timeout=10000)
                page.fill('#term__formControl', diagnosis_code)
                print("Diagnosis code entered successfully.")
                page.click('#findMatchingDiagnosesValidation\\(\\)__button')
                time.sleep(3)
                page.locator('.app-icon.cl-plus-circle-icon.solid').first.click()
                time.sleep(3)

                # === NEW: Check if any question is displayed before proceeding ===
                print("Checking for question sections...")

                question_locator = page.locator('b.ng-binding',
                                                has_text=re.compile(r"Signs|Evaluation|Chest pain|Resting EKG", re.I))

                questions_present = False
                try:
                    question_locator.first.wait_for(timeout=5000)
                    questions_present = True
                except PlaywrightTimeoutError:
                    print("No questions appeared within timeout. Skipping Q&A section.")

                if questions_present:
                    print("Question(s) detected. Proceeding with Q&A flow.")

                    cpt_code = patient.get("cpt_code", "")

                    if cpt_code == "93306":
                        # === 93306 FLOW ===
                        print("Applying workflow for CPT code 93306")
                        page.locator('b.ng-binding',
                                    has_text=re.compile(r"Signs, symptoms, or abnormal test results.*chest pain.*murmur",
                                                        re.I)).first.click()
                        time.sleep(3)
                        page.locator('span.control-caption',
                                    has_text=re.compile("Evaluation of newly recognized symptoms suggestive of heart disease")).click()
                        page.click('#applyAnswerForCheckbox\\(\\)__link')
                        time.sleep(1)
                        page.locator('span.control-caption', has_text=re.compile("Chest pain", re.I)).nth(1).click()
                        page.locator('b.ng-binding', has_text=re.compile("Apply answer", re.I)).nth(1).click()
                        time.sleep(1)
                        page.locator('span.control-caption', has_text=re.compile(r'^No$', re.IGNORECASE)).click()

                    elif cpt_code == "78452":
                        # === 78452 FLOW ===
                        print("Applying workflow for CPT code 78452")
                        page.locator('b.ng-binding',
                                    has_text=re.compile(r"Evaluation of chest pain or other cardiac symptoms", re.I)).click()
                        time.sleep(2)
                        page.locator('span.control-caption', has_text=re.compile(r"Resting EKG", re.I)).click()
                        time.sleep(1)
                        page.click('#applyAnswerForCheckbox\\(\\)__link')
                        time.sleep(1)
                        page.locator('span.control-caption',
                                    has_text=re.compile(r"Left ventricular hypertrophy.*repolarization", re.I)).click()
                        time.sleep(1)
                        page.click('#applyAnswerForCheckbox\\(\\)__link__1')
                        time.sleep(1)
                        page.locator('span.control-caption', has_text=re.compile(r"^No$", re.I)).click()
                        time.sleep(2)

                    elif cpt_code == "78459":
                        # === 78459 FLOW ===
                        print("Applying workflow for CPT code 78459")

                        # Select Evaluation reason
                        page.locator('b.ng-binding',
                            has_text=re.compile(r"Evaluation of chest pain or other cardiac symptoms", re.I)).click()
                        time.sleep(2)

                        # Select Resting EKG findings
                        page.locator('span.control-caption',
                            has_text=re.compile(r"Left ventricular hypertrophy with repolarization abnormality", re.I)).click()
                        time.sleep(1)
                        page.click('#applyAnswerForCheckbox\\(\\)__link')  # Apply EKG finding
                        time.sleep(1)

                        # Answer: EKG abnormalities previously evaluated → No
                        page.locator('span.control-caption',
                            has_text=re.compile(r"^No$", re.I)).click()
                        time.sleep(1)

                        # Answer: PET scan previously done → No
                        page.locator('span.control-caption',
                            has_text=re.compile(r"^No$", re.I)).nth(1).click()
                        time.sleep(1)

                        # Answer: Prior stress imaging → No prior stress imaging...
                        page.locator('span.control-caption',
                            has_text=re.compile(r"No prior stress imaging has been done", re.I)).click()
                        time.sleep(1)

                        # Answer: Ortho/neuro condition present → Orthopedic or neurological impairment
                        page.locator('span.control-caption',
                            has_text=re.compile(r"Orthopedic or neurological impairment", re.I)).click()
                        time.sleep(2)

                    else:
                        print(f"No specific Q&A flow defined for CPT code: {cpt_code}")

                    print("Clicked 'No' radio option.")
                    time.sleep(3)

                else:
                    print("No questions found. Skipping Q&A section.")

                # === Click Next Button Regardless ===
                next_button = page.locator('#questionsForm__submitAnswers\\(\\)__button')
                if next_button.is_visible(timeout=5000):
                    next_button.click()
                    print("Clicked final Next button.")
                    time.sleep(5)
                else:
                    print("Final Next button not found — assuming no more steps.")

            except PlaywrightTimeoutError as pte:
                print(f"Timeout while waiting for element: {pte}")
                diag_error_occurred = True
            except Exception as e:
                print(f"Error in automated workflow: {e}")
                diag_error_occurred = True

            # Only take screenshot and return home if there was an error
            if diag_error_occurred:
                try:
                    take_screenshot(page, f"diag_error_{patient['first_name']}_{patient['last_name']}.png")

                    # Click on Home button
                    home_button = page.locator('#asNavigation_ctl00_hlHome')
                    if home_button.is_visible(timeout=5000):
                        home_button.click()
                        page.wait_for_timeout(5000)
                        print("Returned to Home screen to process next patient.")
                    else:
                        print("Failed to return to Home screen.")
                except Exception as e:
                    print(f"Error returning to home: {e}")

                continue

            # -------------------------
            # 7.14 Continue & Submit Request
            # -------------------------
            try:
                print("Clicking 'Continue' button...")
                page.wait_for_selector('#doneWithExam\\(\\)__button', timeout=15000)
                page.click('#doneWithExam\\(\\)__button')
                print("'Continue' button clicked.")
                page.wait_for_timeout(5000)
                print("Clicking next button...")
                page.wait_for_selector('#next\\(\\)__button', timeout=15000)
                page.click('#next\\(\\)__button')
                print("'Next' button clicked.")
                page.wait_for_timeout(7000)

                # Determine if the patient is CVCP type
                is_cvcp = patient.get("facility_type", "").lower() == "cvcp"
                provider_type = int(patient.get("provider_type", 0))  # FIXED: extract provider_type

                print("Clicking Advanced Search link...")
                page.wait_for_selector('#asSearch_ctl00_lbProviderSearchAdvanced', timeout=15000)
                page.click('#asSearch_ctl00_lbProviderSearchAdvanced')
                print("Advanced Search clicked.")
                page.wait_for_timeout(3000)

                print("Filling facility name...")
                if is_cvcp:
                    # CVCP Facility Details
                    page.fill('#asSearch_ctl00_tbFacilityName', 'CARDIOVASCULAR CARE PROVIDERS INC')
                    print("Filling city...")
                    page.fill('#asSearch_ctl00_tbCity', 'HOUSTON')
                    print("Filling zip code...")
                    page.fill('#asSearch_ctl00_tbZip', '77056')
                else:
                    # Non-CVCP branching based on provider_type
                    if provider_type in [1, 2]:
                        # Original Non-CVCP Facility Details
                        page.fill('#asSearch_ctl00_tbFacilityName', 'MEMORIAL KATY CARDIOLOGY ASSOC')
                        print("Filling city...")
                        page.fill('#asSearch_ctl00_tbCity', 'KATY')
                        print("Filling zip code...")
                        page.fill('#asSearch_ctl00_tbZip', '77493')
                    elif provider_type == 3:
                        # Alternate Non-CVCP Facility Details
                        provider_name_raw = patient.get("provider_name", "")
                        provider_name = provider_name_raw.replace(",", "").strip()
                        page.fill('#asSearch_ctl00_tbFacilityName', provider_name)
                        print(f"Filling facility name: {provider_name}")
                        print("Filling city...")
                        page.fill('#asSearch_ctl00_tbCity', 'WEBSTER')
                        print("Filling zip code...")
                        page.fill('#asSearch_ctl00_tbZip', '77598')
                    else:
                        print(f"Unknown provider_type '{provider_type}' for non-CVCP. Please check the CSV.")
                        # Optional: raise error, skip, or apply fallback logic

                print("Clicking Find button...")
                page.wait_for_selector('#asSearch_ctl00_btnSearch', timeout=15000)
                page.click('#asSearch_ctl00_btnSearch')
                print("Find button clicked.")
                page.wait_for_timeout(3000)

                # =====================================
                # 🔍 Try to select from In-Network results first
                # =====================================
                in_network_success = False

                try:
                    print("Checking for In-Network result...")
                    in_network_button = page.locator('#asPrimary_ctl00_cmdINSearchResNetwork')
                    if in_network_button.is_visible(timeout=5000):
                        print("In-Network result found. Clicking it...")
                        in_network_button.click()
                        page.wait_for_timeout(3000)
                        
                        # Try selecting the facility (In-Network)
                        facility_selector = 'a[id^="asPrimary_ctl00_gvSearchProviders_ctl"][id$="_cmdSelectFacility1"]'
                        facility_link = page.locator(facility_selector)
                        if facility_link.is_visible(timeout=5000):
                            facility_link.click()
                            print("In-Network facility selected.")
                            in_network_success = True  # Mark success
                        else:
                            raise Exception("In-Network facility not found. Falling back to Expanded Search.")
                    else:
                        raise Exception("In-Network button not found. Proceeding to Expanded Search.")
                except Exception as e:
                    print(f"In-Network path failed: {e}")

                if not in_network_success:
                    # Proceed with existing Expanded Search flow
                    print("Clicking 'Expanded Search' button...")
                    page.wait_for_selector('#asPrimary_ctl00_cmdExpOONSearch', timeout=15000)
                    page.click('#asPrimary_ctl00_cmdExpOONSearch')
                    print("'Expanded Search' clicked.")
                    page.wait_for_timeout(3000)

                    print("Selecting the first facility from search results...")
                    first_option_selector = 'tr.datagridrow a[id^="asPrimary_ctl00_gvSearchProviders_ctl"][id$="_cmdSelectFacility1"]'
                    page.wait_for_selector(first_option_selector, timeout=15000)
                    page.locator(first_option_selector).first.click()
                    print("First facility selected.")

                # --- START OF CONDITIONAL REFERRAL LOGIC ---
                found_optional_fields = False
                timeout_seconds = 10  # How long to keep checking for optional fields
                check_interval_ms = 2000  # Check every 2 seconds

                start_time = time.time()

                while time.time() - start_time < timeout_seconds:
                    yes_radio_button = page.locator('#asPrimary_ctl00_rblIsNumber_0')
                    referral_input = page.locator('#asPrimary_ctl00_tbReferralNumber')
                    next_button = page.locator('#asPrimary_ctl00_btnNext')

                    try:
                        if yes_radio_button.is_visible(timeout=1000) or \
                        referral_input.is_visible(timeout=1000) or \
                        next_button.is_visible(timeout=1000):

                            print("Optional fields detected. Processing referral info...")
                            found_optional_fields = True

                            # 1. Click 'Yes' radio button if visible
                            try:
                                if yes_radio_button.is_visible(timeout=2000):
                                    yes_radio_button.click()
                                    print("Clicked 'Yes' radio option.")
                            except PlaywrightTimeoutError:
                                print("'Yes' radio button not found within timeout.")

                            # 2. Fill Referral Number using member_id from CSV if field is visible
                            try:
                                if referral_input.is_visible(timeout=2000):
                                    referral_value = patient.get("member_id", "")
                                    if referral_value:
                                        print(f"Typing referral number: {referral_value}")
                                        referral_input.click()
                                        referral_input.type(referral_value, delay=100)
                                        print(f"Finished typing referral number: {referral_value}")
                                    else:
                                        print("Member ID not found in CSV for referral number.")
                            except PlaywrightTimeoutError:
                                print("Referral number input not found within timeout.")

                            # 3. Click Next button if visible and enabled
                            try:
                                if next_button.is_visible(timeout=2000) and not next_button.is_disabled():
                                    next_button.click()
                                    print("Clicked 'Next' button.")
                                elif next_button.is_visible():
                                    print("'Next' button is disabled.")
                                else:
                                    print("'Next' button not visible.")
                            except PlaywrightTimeoutError:
                                print("'Next' button not found within timeout.")

                            break  # Exit loop after successful action

                        else:
                            print("Optional fields not visible yet. Retrying...")
                            time.sleep(check_interval_ms / 1000)
                    except PlaywrightTimeoutError:
                        print("Timeout occurred during visibility check. Retrying...")
                        time.sleep(check_interval_ms / 1000)

                if not found_optional_fields:
                    print("Optional fields is not appeared. Skipping referral input step.")
                # --- END OF CONDITIONAL REFERRAL LOGIC ---

                # Always continue with these steps
                page.wait_for_timeout(5000)
                print("Clicking 'Continue' button...")
                page.wait_for_selector('#asPrimary_ctl00_btnContinue', timeout=15000)
                page.click('#asPrimary_ctl00_btnContinue')
                print("'Continue' button clicked.")
                page.wait_for_timeout(5000)

                print("Clicking 'Submit This Request' button...")
                page.wait_for_selector('#asPrimary_ctl00_cmdSubmitRequest', timeout=15000)
                page.click('#asPrimary_ctl00_cmdSubmitRequest')
                print("'Submit This Request' button clicked.")
                page.wait_for_timeout(9000)

                # ================================
                # NEW: Download Step + Return to Home
                # ================================
                custom_download_path = r"\\192.168.2.8\eclinical\BENEFITS\MEMORIAL KATY CARDIOLOGY ASSOCIATES\Authorization\Careon"  # Change this to your desired path
                os.makedirs(custom_download_path, exist_ok=True)

                try:
                    print("Starting PDF generation and download...")

                    # Locate the Save as PDF button using its ID
                    pdf_button = page.locator("#asPrimary_ctl00_cmdSavePdf")

                    # Ensure the button is visible before clicking
                    if not pdf_button.is_visible(timeout=10000):
                        raise Exception("PDF save button not visible on the page.")

                    print("Clicking 'Save as PDF' button...")
                    pdf_button.click()
                    page.wait_for_timeout(3000)

                    # Wait for download to start
                    try:
                        with page.expect_download(timeout=30000) as download_info:
                            pdf_button.click()  # Click again just to ensure download starts
                        download = download_info.value
                    except PlaywrightTimeoutError:
                        raise Exception("Download did not start within expected time.")

                    # Generate unique filename using patient info (example)
                    patient_id = patient.get("member_id", f"patient_{int(time.time())}")
                    suggested_filename = download.suggested_filename or "report.pdf"
                    
                    # Create custom filename
                    unique_filename = f"{patient_id}_{suggested_filename}"
                    final_path = os.path.join(custom_download_path, unique_filename)

                    # Save the downloaded file to the custom location
                    download.save_as(final_path)
                    print(f"✅ PDF saved to: {final_path}")

                    # === Navigate back to Home screen after successful download ===
                    print("Returning to Home screen after download...")
                    home_button = page.locator('#asPrimary_ctl00_btnBeginRequest')

                    if home_button.is_visible(timeout=10000):
                        home_button.click()
                        page.wait_for_timeout(5000)  # Wait for navigation
                        print("Returned to Home screen.")
                    else:
                        print("Home button not visible after timeout.")

                except PlaywrightTimeoutError as pte:
                    print(f"Timeout error during download: {pte}")
                except Exception as e:
                    print(f"An error occurred during PDF download or returning to home: {e}")

            except Exception as e:
                screenshot_path = f"error_patient_{i+1}.png"  # Define screenshot_path
                take_screenshot(page, screenshot_path)
                print(f"Error in continuation steps for patient {i+1}: {e}")
                print(f"Screenshot saved to {screenshot_path}")

        # =============================================
        # 8. Final Cleanup & Exit Handler
        # =============================================
        print("All patients processed. Press '=' to exit browser.")
        listener = Listener(on_press=on_press)
        listener.start()
        stop_event.wait()
        context.close()
        browser.close()
        listener.stop()


if __name__ == "__main__":
    run_login()
