from base64 import b64decode
from datetime import datetime
from hashlib import sha256
from time import sleep, time

from selenium.common.exceptions import (ElementNotInteractableException,
                                        NoSuchElementException,
                                        StaleElementReferenceException)
from selenium.webdriver.remote.webdriver import BaseWebDriver

from lbp.constants import digits_base_64
from lbp.frame_context import FrameContext


class LBP(object):
    base_url = "https://www.labanquepostale.fr"
    def __init__(self, driver:BaseWebDriver, user_id:str, user_pwd:str, wait_item_timeout=3) -> None:
        self.driver = driver
        self.wait_item_timeout = wait_item_timeout
        self.__login = (user_id, user_pwd)
        
    def get_home(self) -> None:
        self.driver.get(self.base_url)
        
    def __getitem__(self, key):
        t0 = time()
        while True:
            try:
                if len(key) and key[0]=="#" and " " not in key:
                    return self.driver.find_element_by_css_selector(key)
                else:
                    res = self.driver.find_elements_by_css_selector(key)
                    if len(res)==0:
                        raise NoSuchElementException(key)
                    return res
            except (StaleElementReferenceException, NoSuchElementException) as error:
                if time()-t0 > self.wait_item_timeout:
                    raise TimeoutError(f"Timeout while waiting for {key}") from error
                sleep(0.1)
    
    def frame_context(self, frame_id:str) -> FrameContext:
        return FrameContext(self.driver, frame_id)
    
    @property
    def connected(self) -> bool:
        return self.connexion_button.text != "Me connecter"

    @property
    def connexion_button(self):
        return self["#connect"]
    
    @property
    def digicode_buttons(self):
        while True:
            res = {}
            for i in (self[f"#val_cel_{i}"] for i in range(4*4)):
                hasher = sha256()
                hasher.update(i.screenshot_as_png)
                digest = hasher.hexdigest()[:6]
                if digest in digits_base_64:
                    res[digits_base_64[digest]] = i
            
            if len(res) != 10:
                sleep(0.1)
                continue
            return res
            
    def __enter_password(self) -> None:
        buttons = self.digicode_buttons
        for char in map(int,str(self.__login[1])):
            buttons[char].click()
    
    def send_keys_secure(self, item, keys:str, timeout:float=3) -> None:
        """
        Send keys to the item provided and retry if the item is not interractable
        """
        t0 = time()
        while True:
            try:
                item.send_keys(keys)
                break
            except (StaleElementReferenceException, ElementNotInteractableException) as error:
                if time()-t0 > timeout:
                    raise TimeoutError(f"Timeout while waiting for {item}") from error
                sleep(0.1)
        
    def login(self) -> None:
        self.get_home()
        # Accept cookies if needed
        if element := self['#footer_tc_privacy_button_2']:
            element.click()
        if self.connected:
            return # Nothing to do
        self.connexion_button.click()
        
        # Wait for login form to pop up
        while True:
            iframes = self["iframe"]
            try:
                connexion_iframe = [i for i in iframes if len(i.get_attribute("title") or "")>3]
            except StaleElementReferenceException:
                continue
            if len(connexion_iframe):
                connexion_iframe = connexion_iframe[0]
                break
        
        # Enter login
        with self.frame_context(connexion_iframe):
            user_field = self["#val_cel_identifiant"]
            self.send_keys_secure(user_field, self.__login[0])
            # Enter password
            self.__enter_password()
            self["#valider"].click()
            
    def wait(self, condition, timeout=3):
        t0 = time()
        while not condition():
            if time()-t0 > timeout:
                raise TimeoutError("Timeout while waiting")
            sleep(0.1)
            
    def parse_current_contract(self):
        header = self["#form_liste_comptes h2 span"]
        sold_date,sold = [i.text for i in self["#form_liste_comptes div.infos-cpt>span"]]
        transactions = []
        res = {
            "owner":header[-1].text,
            "type": header[0].text + " "+ header[1].text,
            'account_id':header[0].text.split(" ")[-1],
            "amount_date": datetime.strptime(sold_date.split(" ")[-1], "%d/%m/%Y"),
            "amount": float(sold.split(" ")[1].replace(",",".")),
            "transactions":transactions
        }
        
        # Parse transactions
        n_elements = len(self["#mouvementsTable tbody tr.row"])
        self["#voirHisto"].click()
        sleep(0.5)
        self["#voirHisto"].click()
        self.wait(lambda: len(self["#mouvementsTable tbody tr.row"])>n_elements)
        for row in self["#mouvementsTable tbody tr.row"]:
            cols = row.find_elements_by_css_selector("td")
            transactions.append({
                "date": datetime.strptime(cols[0].text, "%d/%m/%Y"),
                "label": cols[1].text,
                "amount": float(cols[2].text.replace(",",".").replace("€","").replace(" ",""))
            })
        return res
    
    def safe_click(self, item, condition):
        # Re click until the url is not reached
        while True:
            item.click()
            if not condition():
                sleep(0.1)
                continue
            break
    
    def go_to_contract_menus(self):
        self["#menuPrincipalNavigation li"][0].click()
            
    def dump_all_data(self):
        # Going to contracts menu
        self.go_to_contract_menus()
        n_contracts = len(self.contracts_buttons)
        contracts = []
        for contract_index in range(n_contracts):
            self.safe_click(
                self.contracts_buttons[contract_index],
                lambda: self["#mouvementsTable"] is not None
                )
            contracts.append(self.parse_current_contract())
            self.go_to_contract_menus()
            
        return contracts

    @property
    def contracts_buttons(self):
        return self["ul.listeDesCartouches li div.account-data div.title h3"]
        
    def __enter__(self):
        self.login()
        return self
        
    def __exit__(self, *exc_info, **kwargs):
        self.driver.close()
        