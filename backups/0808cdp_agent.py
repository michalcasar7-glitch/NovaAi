# -*- coding: utf-8 -*-
import sys
import time
import undetected_chromedriver as uc
import traceback

def main(url):
    print("Spouštím agenta s Undetected Chromedriver (Selenium)...")
    driver = None
    try:
        options = uc.ChromeOptions()
        # V budoucnu můžeme přidat argument pro profil, pokud bude potřeba
        # options.add_argument(r'--user-data-dir=C:\path\to\your\profile')
        
        driver = uc.Chrome(options=options)
        
        driver.get(url)
        print(f"Stránka {url} je otevřená. Agent nyní čeká...")
        
        # Smyčka, která udrží proces a okno naživu
        while True:
            time.sleep(1)
            
    except Exception as e:
        print(f"\n\n----- DOSLO K CHYBE -----\n{e}\n------------------------")
        traceback.print_exc()
    finally:
        # Zajistíme, že se okno nezavře hned po chybě a můžeme si přečíst log
        input("\nStiskněte Enter pro ukončení...")
        if driver:
            driver.quit()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Chyba: Zadejte URL jako argument.")
        sys.exit(1)
    
    target_url = sys.argv[1]
    main(target_url)