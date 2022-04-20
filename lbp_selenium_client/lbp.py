from datetime import datetime
from hashlib import sha256
from time import sleep, time

from selenium.common.exceptions import (ElementNotInteractableException,
                                        NoSuchElementException,
                                        StaleElementReferenceException)
from selenium.webdriver.remote.webdriver import BaseWebDriver
from selenium.webdriver.common.by import By
from lbp_selenium_client.constants import digits_base_64
from lbp_selenium_client.frame_context import FrameContext


class LBP(object):
    base_url = "https://www.labanquepostale.fr"
    def __init__(self, driver:BaseWebDriver, user_id:str, user_pwd:str, wait_item_timeout=10) -> None:
        self.driver = driver
        driver.maximize_window()
        self.wait_item_timeout = wait_item_timeout
        self.__login = (user_id, user_pwd)
        
    def get_home(self) -> None:
        self.driver.get(self.base_url)
        
    def __getitem__(self, key):
        return self.get_element(key)
                
    def get_element(self, key:str, timeout=None):
        if timeout is None:
            timeout=self.wait_item_timeout
        t0 = time()
        while True:
            try:
                if len(key) and key[0]=="#" and " " not in key:
                    return self.driver.find_element(by=By.CSS_SELECTOR, value=key)
                else:
                    res = self.driver.find_elements(by=By.CSS_SELECTOR, value=key)
                    if len(res)==0:
                        raise NoSuchElementException(key)
                    return res
            except (StaleElementReferenceException, NoSuchElementException) as error:
                if timeout==0:
                    return None
                
                if time()-t0 > timeout:
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
        amount_date,amount = [i.text for i in self["#form_liste_comptes div.infos-cpt>span"]]
        transactions = []
        res = {
            "owner":header[-1].text,
            "type": header[0].text.replace("\n", " ").split(" N°")[0],
            'account_id':header[0].text.split(" ")[-1],
            "amount_date": datetime.strptime(amount_date.split(" ")[-1], "%d/%m/%Y"),
            "amount": float(amount.replace(" ","").replace(",",".")[:-1]),
            "transactions":transactions
        }
        
        # Parse transactions
        try:
            self.safe_click(
                "#voirHisto",
                lambda: "e-relev" in self["#voirHisto"].text
            )
        except TimeoutError:
            pass
        for row in self["#mouvementsTable tbody tr.row"]:
            cols = row.find_elements_by_css_selector("td")
            transactions.append({
                "date": datetime.strptime(cols[0].text, "%d/%m/%Y"),
                "label": cols[1].text,
                "amount": float(cols[2].text.replace(",",".").replace("€","").replace(" ",""))
            })
        return res
    
    def safe_click(self, item, condition, retry_interval=1, sleep_interval=0.1):
        # Re click until the url is not reached
        while True:
            last_retry = 0
            try:
                if time()- last_retry > retry_interval:
                    last_retry = time()
                    if type(item) == str:
                        self[item].click()
                    else:
                        item.click()
                    
                if not condition():
                    sleep(sleep_interval)
                    continue
                break
            
            except (StaleElementReferenceException, ElementNotInteractableException):
                sleep(sleep_interval)
                continue
    
    def go_to_contract_menus(self):
        self["#lienMenuTertaire1"].click()
        
    def wait_ready(self):
        while self.driver.execute_script('return document.readyState;') != "complete":
            sleep(0.1)
        
    def dump_all_data(self):
        contracts = []
        
        for menu_index in range(1,3):
            key=f"#lienMenuTertaire{menu_index}"
            # Going to contracts menu
            self.safe_click(
                key,
                lambda: self.get_element("div.account-data", timeout=0) is not None
            )
            n_contracts = len(self.contracts_buttons)
            
            # Dump accounts
            for contract_index in range(n_contracts):
                self.safe_click(
                    self.contracts_buttons[contract_index],
                    lambda: self.get_element("#mouvementsTable", timeout=0) is not None
                    )
                contracts.append(self.parse_current_contract())
                self[key].click()
                
        return contracts

    @property
    def contracts_buttons(self):
        return self["ul.listeDesCartouches li div.account-data div.title h3"]
        
    def __enter__(self):
        self.login()
        return self
        
    def __exit__(self, *exc_info, **kwargs):
        self.driver.close()
        