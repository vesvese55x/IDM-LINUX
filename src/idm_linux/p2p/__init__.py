"""IDM-Linux kendi P2P motorları (sıfırdan, saf Python).

Bu paket HİÇBİR üçüncü taraf istemci (aria2c, aMule, mldonkey, transmission)
kullanmaz: BitTorrent (BEP 3/5/6/9/10/11/19) ve eD2K/eMule protokolleri burada
kendi kodumuzla konuşulur.

Modüller:
  * :mod:`bencode`      — BEP 3 kodlayıcı/çözücü (span bilgisiyle; info-hash için)
  * :mod:`tracker`      — HTTP(S) + UDP (BEP 15) tracker anonsları
  * :mod:`dht`          — BEP 5 Kademlia DHT (magnet meta verisi için eş bulma)
  * :mod:`bt_native`    — saf Python BitTorrent oturumu (parça seçici, eş teli,
                          ut_metadata ile magnet çözümü, aria2 uyumlu durum)
  * :mod:`md4`          — saf Python MD4 (eD2K hash'leri; OpenSSL 3 kaldırdı)
  * :mod:`ed2k_native`  — saf Python eD2K/eMule istemcisi (sunucu listesi, kaynak
                          sorgusu, eş el sıkışması, parça indirme, MD4 doğrulama)
"""

__all__ = ["bencode", "tracker", "dht", "bt_native", "ed2k_native", "md4"]
