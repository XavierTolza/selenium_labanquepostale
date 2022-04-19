from selenium.webdriver.remote.webdriver import BaseWebDriver

class FrameContext(object):
    def __init__(self, driver:BaseWebDriver, frame) -> None:
        self.driver = driver
        self.frame = frame
        
    def __enter__(self):
        self.driver.switch_to.frame(self.frame)
        return self
    
    def __exit__(self, *exc_info, **kwargs):
        self.driver.switch_to.default_content()