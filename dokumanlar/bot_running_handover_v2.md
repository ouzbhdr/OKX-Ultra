# 🤖 OKX Ultra - Devir Teslim Raporu (Versiyon 2)

Bu doküman, botun 15 Dakikalık (15M) zaman dilimine geçişini, sabit optimizasyon takvimini, yeni parite entegrasyonlarını ve yerel düzenlemeleri özetleyen güncel kılavuzdur.

---

## 1. Versiyon 2 ile Yapılan Yenilikler ve Değişiklikler

> [!IMPORTANT]
> **15M Zaman Dilimine Geçiş:** Botun işlem sıklığını artırarak bileşik kâr hızını ivmelendirmek amacıyla tüm analiz ve emir tetikleme mekanizmaları 1 Saatlik (1H) periyottan 15 Dakikalık (15M) periyoda çekilmiştir.

* **Dinamik 168/720 Mum Oranı Korundu:**
  * **Analiz Penceresi (Lookback):** 720 bar (15 dakikalık barlarla tam olarak 7.5 güne denk gelir).
  * **Optimizasyon Sıklığı (WFO Step):** 168 bar (15 dakikalık barlarla tam olarak 42 saat / 1.75 güne denk gelir).
* **Sabit Optimizasyon Takvimi:**
  Rastgele saatlerde optimizasyon çalışmasını önlemek için haftalık 168 saatlik süre kalansız olarak 42 saatlik 4 eşit parçaya bölündü. Bot artık her hafta şu sabit saatlerde optimizasyonu otomatik tetikler:
  1. **Pazartesi 03:00**
  2. **Salı 21:00**
  3. **Perşembe 15:00**
  4. **Cumartesi 09:00**
* **Kesinti Koruma Sistemi (last_scan.txt):**
  Sunucu kapansa veya elektrik kesilse dahi bot uyanırken en yakın geçmişteki hedef zamanı kontrol eder. Eğer tarama süresi geçmişse otomatik olarak hemen tarama yapar ve takvimi tekrar sabitler.
* **Yeni Hacimli Pariteler Eklendi:**
  Listeye OKX Swap piyasasının en yüksek hacimli ve oynak kripto paralarından **`WLD-USDT-SWAP`** ve **`HYPE-USDT-SWAP`** eklenerek toplam aktif takip edilen coin sayısı **9**'a çıkarıldı.

---

## 2. Güncel Dosya ve Dizin Yapısı (Yerel PC)

Dizin dağınıklığını önlemek için yerel `D:\OKX Ultra` klasörü aşağıdaki gibi kategorize edilmiştir:

```
D:\OKX Ultra\
├── anahtarlar\          # VPS sunucusuna ait SSH bağlantı anahtarları (.key ve .pub)
├── veriler\             # Borsa geçmiş veri önbellekleri (cache_*.csv) ve target_coins.txt
├── kodlar\              # Python kaynak kod dosyaları (run_bot.py, mando.py, solo.py vb.)
├── dokumanlar\          # Mimari şemalar, sql şeması ve devir teslim .md dosyaları
└── requirements.txt     # Python kütüphane bağımlılıkları listesi
```

---

## 3. Canlı Sunucu (VPS) Yapılandırması

* **Sunucu IP:** `89.168.120.233` (Oracle Cloud Frankfurt)
* **Bağlantı Anahtarı:** `D:\OKX Ultra\anahtarlar\ssh-key-2026-07-03.key`
* **Bot Dizin Yolu:** `/home/ubuntu/okx_ultra/`
* **Çalışma Şekli (Systemd Servisi):**
  Bot, sunucu kapansa dahi otomatik yeniden açılan `/etc/systemd/system/okx_ultra.service` servisi olarak arka planda çalışmaktadır.
  * **Servisi Yeniden Başlatma:** `sudo systemctl restart okx_ultra.service`
  * **Logları Canlı İzleme:** `journalctl -u okx_ultra.service -f`

---

## 4. Telegram Bot Kontrol Komutları

Botunuz açık olduğu sürece Telegram üzerinden şu komutları kabul eder:

| Komut | İşlev |
| :--- | :--- |
| `/durum` | Bot çalışma durumunu, bakiyeyi, aktif işlemleri ve pariteleri gösterir. |
| `/baslat` | Sunucudaki bot motorunu çalıştırır. |
| `/dur` | Bot motorunu durdurur (açık pozisyonlara dokunmaz, yeni sinyal aramayı keser). |
| `/sanalmod` | OKX Sanal (Demo) işlem moduna geçer. |
| `/gercekmod` | OKX Gerçek para ile işlem moduna geçer. |
| `/tekislem` | Aynı anda sadece tek işlem limitini açıp kapatır (Açık/Kapalı). |
| `/tara` | 42 saatlik sabit takvimi beklemeden o an manuel optimizasyonu başlatır. |
| `/karaliste` | Kasa yetersizliği nedeniyle Jawa tarafından geçici yasaklanan coinleri listeler. |
| `/ekle <parite>` | Takip listesine yeni bir vadeli işlem çifti ekler. |
| `/cikar <parite>` | Takip listesinden bir vadeli işlem çiftini çıkartır. |

---

## 5. Güvenlik ve Dikkat Edilmesi Gerekenler

> [!WARNING]
> **Hesap Modu Uyuşmazlığı:** Kaldıraçlı Swap emirlerinin OKX tarafından reddedilmemesi için borsa arayüzünden hesap modunun **"Single-currency margin" (Tek para birimi teminatı)** veya **"Multi-currency margin" (Çoklu para birimi teminatı)** olarak ayarlanmış olması şarttır.

> [!TIP]
> **Kasa Yönetimi:** Kasa bakiyesi küçük olduğu sürece ($20 altı) riskinizi dağıtmak amacıyla Telegram'dan `/tekislem` modunun **Açık** tutulması önerilir. Bakiye büyüdükçe bu sınır kapatılarak eş zamanlı çoklu işleme izin verilebilir.
