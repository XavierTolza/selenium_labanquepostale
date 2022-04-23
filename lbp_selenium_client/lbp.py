import io
from datetime import datetime
from hashlib import sha256
from time import sleep, time

import numpy as np
from iteration_utilities import grouper
from PIL import Image
from selenium.common.exceptions import (ElementNotInteractableException,
                                        NoSuchElementException,
                                        StaleElementReferenceException)
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import BaseWebDriver

from lbp_selenium_client.constants import digits_base_64
from lbp_selenium_client.frame_context import FrameContext


class LBP(object):
    base_url = "https://www.labanquepostale.fr"
    def __init__(self, driver:BaseWebDriver, user_id:str, user_pwd:str, 
                 wait_item_timeout=10, wait_click_timeout=15, logger=None) -> None:
        self.driver = driver
        driver.maximize_window()
        self.logger = logger
        self.wait_item_timeout = wait_item_timeout
        self.wait_click_timeout = wait_click_timeout
        self.__login = (user_id, user_pwd)
        
    def debug(self, msg):
        """
        If the logger exists, log the message
        
        :param msg: The message to be logged
        """
        if self.logger:
            self.logger.debug(msg)
            
    def info(self, msg):
        if self.logger:
            self.logger.info(msg)
            
    def warning(self, msg):
        if self.logger:
            self.logger.warning(msg)
            
    def error(self, msg):
        if self.logger:
            self.logger.error(msg)
        
    def get_home(self) -> None:
        self.debug("Getting home")
        self.driver.get(self.base_url)
        
    def __getitem__(self, key):
        return self.get_element(key)
                
    def get_element(self, key:str, timeout=None):
        if timeout is None:
            timeout=self.wait_item_timeout
        t0 = time()
        message_displayed=False
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
                if not message_displayed:
                    self.debug(f"Waiting for {key}")
                    message_displayed=True
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
        keys = np.array(list(digits_base_64.keys()))
        values = list(digits_base_64.values())
        while True:
            res = {}
            for i in (self[f"#val_cel_{i}"] for i in range(4*4)):
                img = Image.open(io.BytesIO(i.screenshot_as_png))
                img = np.array(img)
                digest = img.mean()
                
                index = np.argmin(np.abs(keys-digest))
                
                if (value:=values[index]) is not None:
                    res[value] = i
            
            if len(res) != 10:
                sleep(0.1)
                continue
            return res
            
    def __enter_password(self) -> None:
        self.debug("Entering password")
        buttons = self.digicode_buttons
        for char in map(int,str(self.__login[1])):
            buttons[char].click()
    
    def send_keys_secure(self, item, keys:str, timeout:float=None) -> None:
        """
        Send keys to the item provided and retry if the item is not interractable
        """
        if timeout is None:
            timeout = self.wait_click_timeout
            
        t0 = time()
        while True:
            try:
                if isinstance(item, str):
                    self[item].send_keys(keys)
                else:
                    item.send_keys(keys)
                break
            except (StaleElementReferenceException, ElementNotInteractableException) as error:
                if time()-t0 > timeout:
                    raise TimeoutError(f"Timeout while waiting for {item}") from error
                sleep(0.1)
        
    def login(self) -> None:
        self.info("Logging in")
        self.get_home()
        # Accept cookies if needed
        if element := self['#footer_tc_privacy_button_2']:
            self.debug("Accepting cookies")
            element.click()
        if self.connected:
            self.debug("Already connected")
            return # Nothing to do
        self.connexion_button.click()
        
        # Wait for login form to pop up
        self.debug("Waiting for login iframe")
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
            self.debug("Entering login")
            self.send_keys_secure("#val_cel_identifiant", self.__login[0])
            # Enter password
            self.__enter_password()
            self["#valider"].click()
            
    def wait(self, condition, timeout=3):
        t0 = time()
        message_printed = False
        while not condition():
            if time()-t0 > timeout:
                raise TimeoutError("Timeout while waiting")
            if not message_printed:
                message_printed=True
                self.debug(f"Waiting for condition {condition}")
            sleep(0.1)
        if message_printed:
            self.debug("Condition met")
            
    def parse_current_contract(self):
        self.info("Parsing current contract")
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
        self.debug(f"Current contract is {res['account_id']}")
        
        # Parse transactions
        try:
            self.debug("Expanding transactions list")
            self.get_element("#voirHisto", 1)
            self.safe_click(
                "#voirHisto",
                lambda: "e-relev" in self.get_element("#voirHisto", 0).text
            )
        except TimeoutError:
            self.debug("No transactions list expansion")
            
        self.debug("Parsing transactions")
        for cols in grouper((i.text for i in self["#mouvementsTable tbody tr.row td"]),4):
            transactions.append({
                "date": datetime.strptime(cols[0], "%d/%m/%Y"),
                "label": cols[1],
                "amount": float(cols[2].replace(",",".").replace("€","").replace(" ",""))
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
        