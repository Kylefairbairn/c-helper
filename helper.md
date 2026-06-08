example of tls 

// mtls_client.cpp

#include <openssl/ssl.h>
#include <openssl/err.h>
#include <openssl/store.h>
#include <openssl/evp.h>

#include <iostream>
#include <string>

EVP_PKEY* load_private_key_from_uri(const char* key_uri) {
    OSSL_STORE_CTX* store = OSSL_STORE_open(
        key_uri,
        nullptr,
        nullptr,
        nullptr,
        nullptr
    );

    if (!store) {
        std::cerr << "OSSL_STORE_open failed\n";
        ERR_print_errors_fp(stderr);
        return nullptr;
    }

    EVP_PKEY* pkey = nullptr;

    while (!OSSL_STORE_eof(store)) {
        OSSL_STORE_INFO* info = OSSL_STORE_load(store);

        if (!info) {
            ERR_print_errors_fp(stderr);
            break;
        }

        if (OSSL_STORE_INFO_get_type(info) == OSSL_STORE_INFO_PKEY) {
            pkey = OSSL_STORE_INFO_get1_PKEY(info);
            OSSL_STORE_INFO_free(info);
            break;
        }

        OSSL_STORE_INFO_free(info);
    }

    OSSL_STORE_close(store);
    return pkey;
}

int main() {
    const char* host = "127.0.0.1";
    const char* port = "8443";

    const char* cert_file = "client.crt";

    const char* key_uri =
        "pkcs11:token=nets-token;object=nats-server_key;type=private";

    SSL_CTX* ctx = SSL_CTX_new(TLS_client_method());

    if (!ctx) {
        std::cerr << "Failed to create SSL_CTX\n";
        ERR_print_errors_fp(stderr);
        return 1;
    }

    if (SSL_CTX_use_certificate_file(ctx, cert_file, SSL_FILETYPE_PEM) != 1) {
        std::cerr << "Failed to load client certificate\n";
        ERR_print_errors_fp(stderr);
        SSL_CTX_free(ctx);
        return 1;
    }

    EVP_PKEY* private_key = load_private_key_from_uri(key_uri);

    if (!private_key) {
        std::cerr << "Failed to load PKCS#11 private key\n";
        SSL_CTX_free(ctx);
        return 1;
    }

    if (SSL_CTX_use_PrivateKey(ctx, private_key) != 1) {
        std::cerr << "Failed to attach private key to SSL_CTX\n";
        ERR_print_errors_fp(stderr);
        EVP_PKEY_free(private_key);
        SSL_CTX_free(ctx);
        return 1;
    }

    EVP_PKEY_free(private_key);

    if (SSL_CTX_check_private_key(ctx) != 1) {
        std::cerr << "Certificate does not match private key\n";
        ERR_print_errors_fp(stderr);
        SSL_CTX_free(ctx);
        return 1;
    }

    BIO* bio = BIO_new_ssl_connect(ctx);

    std::string target = std::string(host) + ":" + port;
    BIO_set_conn_hostname(bio, target.c_str());

    if (BIO_do_connect(bio) <= 0) {
        std::cerr << "TLS connection failed\n";
        ERR_print_errors_fp(stderr);
        BIO_free_all(bio);
        SSL_CTX_free(ctx);
        return 1;
    }

    std::cout << "mTLS connection succeeded\n";

    BIO_free_all(bio);
    SSL_CTX_free(ctx);

    return 0;
}
