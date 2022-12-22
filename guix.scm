(define-module (guix)
#:use-module (guix packages)
#:use-module ((guix licenses) #:prefix license:)
#:use-module (guix build-system python)
#:use-module (guix build-system gnu)
#:use-module (guix git-download)
#:use-module (guix download)
#:use-module (guix search-paths)
#:use-module (gnu packages)
#:use-module (gnu packages pkg-config)
#:use-module (gnu packages autotools)
#:use-module (gnu packages certs)
#:use-module (gnu packages check)
#:use-module (gnu packages databases)
#:use-module (gnu packages gnupg)
#:use-module (gnu packages wget)
#:use-module (gnu packages python)
#:use-module (gnu packages python-build)
#:use-module (gnu packages python-crypto)
#:use-module (gnu packages python-xyz)
#:use-module (gnu packages libffi)
#:use-module (gnu packages license))


(define-public python-plyvel
  (package
    (name "python-plyvel")
    (version "1.5.0")
    (source
     (origin
       (method url-fetch)
       (uri (pypi-uri "plyvel" version))
       (sha256
        (base32 "0ar0z53nhi9q3kvpmpkk2pzb46lmmwn79a02sb9vq2k9645qx4fd"))))
    (build-system python-build-system)
    (inputs
     (list leveldb))
    (native-inputs
     (list pkg-config python-cython python-pytest))
    (home-page "https://github.com/wbolster/plyvel")
    (synopsis "Python bindings for 0MQ")
    (description
     "Plyvel is a fast and feature-rich Python interface to LevelDB.")
    (license license:bsd-4)))


(define-public particl-coldstakepool
(package
  (name "particl-coldstakepool")
  (version "0.11.55")
  (source (origin
    (method git-fetch)
    (uri (git-reference
      (url "https://github.com/tecnovert/particl-coldstakepool")
      (commit "ab01e10f328f49e3dfb9227924a837d0985a41bb")))
    (sha256
      (base32
        "04h3pp5ncgg3fixwxbwnzd1gdil9f9dfj26y17571qcyj2k8j5y2"))
    (file-name (git-file-name name version))))
  (build-system python-build-system)

  (native-search-paths (list $SSL_CERT_DIR $SSL_CERT_FILE))
  (arguments
     '(#:tests? #f ; TODO: Add coin binaries
       ))
  (propagated-inputs
   (list
    gnupg
    wget
    leveldb
    nss-certs
    python-pytest
    python-pyzmq
    python-gnupg
    python-plyvel
    ))
  (native-inputs
   (list
    python-setuptools
    python-wheel
    python-pylint
    python-pyflakes
    ))
  (synopsis "Particl Cold-Staking Pool - Proof of concept")
  (description #f)
  (home-page "https://github.com/tecnovert/particl-coldstakepool")
  (license license:bsd-3)))


