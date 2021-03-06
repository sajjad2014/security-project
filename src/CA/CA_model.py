import os
import random

import requests
from OpenSSL import crypto
from cryptography.hazmat.backends.openssl.backend import backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding

from src.shared_data import SharedData


class CAUserDataModel:
    def __init__(self, gmail):
        self.gmail = gmail
        self.public_cert_list = {}  # key: public key, value:certification
        # certification request state
        self.last_verification_code = None
        self.last_public_key_cert_request: str = None


class CA:
    # crypto file addresses
    _ca_certificate_address = os.path.join(os.getcwd(), "ca_self_signed_cert.crt")
    _ca_private_address = os.path.join(os.getcwd(), "private.key")
    _ca_public_address = os.path.join(os.getcwd(), "public.key")

    @property
    def _public_key_object(self):
        return serialization.load_pem_public_key(
            self._pub_key.encode('utf-8'),
            backend=backend
        )

    @property
    def _private_key_object(self):
        return serialization.load_pem_private_key(
            self._pri_key.encode('utf-8'),
            backend=backend,
            password=None
        )

    @classmethod
    def _generate_random_code(self):
        return str(random.randint(100000, 999999))

    def __init__(self):
        # ca mail detail
        self._sender_mail = input("Enter ca gmail:")
        self._sender_password = input("Enter ca gmail password:")
        # initialize crypto stuff
        self._pub_key, self._pri_key, self._cert = self._create_keys_and_self_signed_certificate()
        # fields
        self._users_data = {}  # key:id(gmail), value:UserDataModel

    def incoming_certificate_request(self, data):
        gmail = data['gmail']
        user_public_key = data['user_public_key']
        rand_string = self._generate_random_code()
        encrypted_rand_string = self._public_key_object.encrypt(
            rand_string.encode('utf-8'),
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        # send encrypted verification mail
        print(rand_string)
        # self._send_mail(gmail, encrypted_rand_string)

        # update user model data
        user_data_model: CAUserDataModel = self._users_data.get(gmail, CAUserDataModel(gmail))
        self._users_data[gmail] = user_data_model
        user_data_model.last_verification_code = rand_string
        user_data_model.last_public_key_cert_request = user_public_key

        user_url = SharedData.sections_url_address[SharedData.Entities.User]

        requests.post(user_url, json={"verification": encrypted_rand_string})
        return encrypted_rand_string

    def incoming_response_verification_code(self, data):
        gmail = data['gmail']
        verification_code = data['verification_code']
        user_data_model: CAUserDataModel = self._users_data.get(gmail, None)
        if user_data_model:
            if verification_code == user_data_model.last_verification_code:
                requested_pub_key = user_data_model.last_public_key_cert_request
                cert = self._sign_user_certificate(requested_pub_key, gmail)
                user_data_model.public_cert_list[requested_pub_key] = cert

                user_url = SharedData.sections_url_address[SharedData.Entities.User]
                requests.post(user_url, json={"cert": cert})
                return cert
        return None

    # def _send_mail(self, receiver_gmail, message):
    #     import smtplib, ssl
    #
    #     port = 465  # For SSL
    #     smtp_server = "smtp.gmail.com"
    #
    #     context = ssl.create_default_context()
    #     with smtplib.SMTP_SSL(smtp_server, port, context=context) as server:
    #         server.login(self._sender_mail, self._sender_password)
    #         server.sendmail(self._sender_mail, receiver_gmail, message)
    #         print("sent to: ", receiver_gmail)
    #         print("message:\n", message)

    def _sign_user_certificate(self, user_public_key: str, user_mail: str):
        ca_cert = crypto.load_certificate(crypto.FILETYPE_PEM, self._cert)
        ca_private_key = crypto.load_privatekey(crypto.FILETYPE_PEM, self._pri_key)

        user_pem_pub_key = serialization.load_pem_public_key(user_public_key.encode('utf-8'), backend)
        user_pkey_just_public = crypto.PKey()
        user_pkey_just_public = user_pkey_just_public.from_cryptography_key(user_pem_pub_key)

        #
        cert_req = crypto.X509Req()
        cert_req.get_subject().C = "IR"
        cert_req.get_subject().ST = "state"
        cert_req.get_subject().L = "location"
        cert_req.get_subject().O = "organization"
        cert_req.get_subject().CN = "Temporary Certificate"
        cert_req.get_subject().emailAddress = user_mail
        #
        cert_req.set_pubkey(user_pkey_just_public)
        cert_req.sign(ca_private_key, 'sha256')
        # print(crypto.dump_certificate(crypto.FILETYPE_TEXT, cert_req))
        #
        cert = crypto.X509()
        cert.gmtime_adj_notBefore(0)
        cert.gmtime_adj_notAfter(5 * 365 * 24 * 60 * 60)
        cert.set_issuer(ca_cert.get_subject())
        cert.set_subject(cert_req.get_subject())
        cert.set_pubkey(cert_req.get_pubkey())
        cert.sign(ca_private_key, 'sha256')
        user_cert = crypto.dump_certificate(crypto.FILETYPE_TEXT, cert)
        return user_cert

    def _create_keys_and_self_signed_certificate(self):
        # create a key pair
        k = crypto.PKey()
        k.generate_key(crypto.TYPE_RSA, 1024)
        # create a self-signed cert
        cert = crypto.X509()
        cert.get_subject().C = "IR"
        cert.get_subject().ST = "state"
        cert.get_subject().L = "location"
        cert.get_subject().O = "organization"
        cert.get_subject().CN = "Temporary Certificate"
        cert.get_subject().emailAddress = self._sender_mail
        cert.set_serial_number(0)
        cert.gmtime_adj_notBefore(0)
        cert.gmtime_adj_notAfter(10 * 365 * 24 * 60 * 60)
        cert.set_issuer(cert.get_subject())
        cert.set_pubkey(k)
        cert.sign(k, 'sha512')
        with open(self._ca_certificate_address, "wt") as f1:
            self_signed_cert_utf = crypto.dump_certificate(crypto.FILETYPE_PEM, cert).decode("utf-8")
            f1.write(self_signed_cert_utf)
        with open(self._ca_private_address, "wt") as f2:
            private_key_utf = crypto.dump_privatekey(crypto.FILETYPE_PEM, k).decode("utf-8")
            f2.write(private_key_utf)
        with open(self._ca_public_address, "wt") as f3:
            public_key_utf = crypto.dump_publickey(crypto.FILETYPE_PEM, cert.get_pubkey()).decode("utf-8")
            f3.write(public_key_utf)
        return public_key_utf, private_key_utf, self_signed_cert_utf
