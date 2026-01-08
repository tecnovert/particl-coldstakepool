(define-module (guix)
#:use-module (guix packages)
#:use-module ((guix licenses) #:prefix license:)
#:use-module (guix build-system gnu)
#:use-module (guix build-system python)
#:use-module (guix download)
#:use-module (guix git-download)
#:use-module (guix search-paths)
#:use-module (gnu packages autotools)
#:use-module (gnu packages certs)
#:use-module (gnu packages check)
#:use-module (gnu packages databases)
#:use-module (gnu packages gnupg)
#:use-module (gnu packages libffi)
#:use-module (gnu packages license)
#:use-module (gnu packages nss)
#:use-module (gnu packages pkg-config)
#:use-module (gnu packages python)
#:use-module (gnu packages python-build)
#:use-module (gnu packages python-check)
#:use-module (gnu packages python-crypto)
#:use-module (gnu packages python-xyz)
#:use-module (gnu packages wget)
#:use-module (gnu packages))


(define-public python-plyvel
  (package
    (name "python-plyvel")
    (version "1.5.1")
    (source
     (origin
       (method url-fetch)
       (uri (pypi-uri "plyvel" version))
       (sha256
        (base32 "17018r7c73r1c4hxz2544rf4jmkyvbrmwgrdf7wgn97wwh4n1brw"))))
    (build-system python-build-system)
    (arguments
      (list #:tests? #f)) ; Disable the tests phase - test removed from setuptools
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
  (version "0.24.0")
  (source (origin
    (method git-fetch)
    (uri (git-reference
      (url "https://github.com/tecnovert/particl-coldstakepool")
      (commit "488b9c71e4a0be3081bad8ae620f62d3f05f290c")))
    (sha256
      (base32
        "0rinw1l29kd5f4wsaasq4vbf4pngr64nbjfrn3q09fyg12awy4jl"))
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


