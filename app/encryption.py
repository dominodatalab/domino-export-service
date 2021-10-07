from cryptography.fernet import Fernet

class Encrypter(object):
    def __init__(self):
        self.__encrypter = None
        self.__cryptKey = None

    def setKey(self, key):
        if self.__encrypter == None:
            self.__cryptKey = key
            self.__encrypter = Fernet(self.__cryptKey)

    def setKeyFile(self, keyFile):
        try:
            with open(keyFile, "rb") as cryptKeyFile:
                cryptKey = cryptKeyFile.read()
                self.setKey(cryptKey)
        except FileNotFoundError:
            with open(keyFile, "wb") as cryptKeyFile:
                cryptKey = Fernet.generate_key()
                cryptKeyFile.write(cryptKey)
                self.setKey(cryptKey)
        except:
            raise

    def encrypt(self, data):
        __encrypted = None
        if self.__encrypter != None:
            __data = data
            # Convert to bytes if needed
            if type(data) == str:
                __data = data.encode("utf-8")

            __encrypted = self.__encrypter.encrypt(__data).decode("utf-8")

        return __encrypted

    def decrypt(self, data):
        __decrypted = None
        if self.__encrypter != None:
            __data = data
            # Convert to bytes if needed
            if type(data) == str:
                __data = data.encode("utf-8")
            __decrypted = self.__encrypter.decrypt(__data).decode("utf-8")

        return __decrypted