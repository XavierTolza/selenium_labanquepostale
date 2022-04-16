from selenium.webdriver.remote.webdriver import BaseWebDriver
from selenium.common.exceptions import StaleElementReferenceException
from lbp.frame_context import FrameContext

class LBP(object):
    base_url = "https://www.labanquepostale.fr"
    def __init__(self, driver:BaseWebDriver, user_id:str, user_pwd:str) -> None:
        self.driver = driver
        self.__login = (user_id, user_pwd)
        
    def get_home(self) -> None:
        self.driver.get(self.base_url)
        
    def __getitem__(self, key):
        if len(key) and key[0]=="#":
            return self.driver.find_element_by_css_selector(key)
        else:
            return self.driver.find_elements_by_css_selector(key)
    
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
        return [self[f"val_cel_{i}"] for i in range(4*4)]
    
    def __enter_password(self) -> None:
        buttons = self.digicode_buttons
        raise NotImplementedError()
        
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
            self["#val_cel_identifiant"].send_keys(self.__login[0])
            # Enter password
            self.__enter_password()
            raise NotImplementedError()
        
    def __enter__(self):
        self.login()
        
    def __exit__(self, *exc_info, **kwargs):
        self.driver.close()
        