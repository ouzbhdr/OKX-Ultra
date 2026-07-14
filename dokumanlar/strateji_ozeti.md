# OKX Ultra — Guncel Strateji Ozeti
**Son Guncelleme:** 7 Temmuz 2026
**Versiyon:** V1 Mantigi + 15M Zaman Dilimi

---

## 1. Genel Mantik

```
Buyuk Trend (MOST) -> Duzeltme Donusu (IFTStoch) -> Giris -> Trailing Stop ile Cikis
```

Sistem trend yonunde giriyor, kucuk duzeltmelerden ucuza aliyor (veya pahaliya shortuyor), trend bozulana kadar trailing stop ile takip ediyor.

---

## 2. Kullanilan Indikatorler

### MOST (Moving Stop)
- EMA hesaplar, EMA'nin belirli % altinda/ustunde takip cizgisi olusturur.
- `EMA > MOST cizgisi (line2)` -> LONG trendi
- `EMA < MOST cizgisi (line1)` -> SHORT trendi
- Trend degisimi -> K1 (LONG'a gecis) veya K2 (SHORT'a gecis) sinyali uretir.

### IFTStoch (Inverse Fisher Transform Stochastic)
- Stochastic osilatorunun Fisher donusumuyle normalize edilmis hali.
- -1 ile +1 arasinda deger alir.
- LONG icin asiri satim: -0.5 alti
- SHORT icin asiri alim: +0.5 ustu

---

## 3. Giris Sinyali

### LONG Girisi — 3 kosulun tamami saglanmali:
1. MOST trendi LONG (EMA > line2)
2. K1 trend donusunden bu yana <= 20 bar gecmis olmali
3. IFT penceresi (K1'den 3 bar once - simdi arasi): en az 2 bar -0.5 altinda + en az 1 bar -0.5 ustunde (Barlarin ardisik olmasi zorunlu degildir, toplam adet yeterlidir)

### SHORT Girisi — ayni mantik ters yone:
1. MOST trendi SHORT (EMA < line1)
2. K2 trend donusunden bu yana <= 20 bar gecmis olmali
3. IFT penceresi: en az 2 bar +0.5 ustunde + en az 1 bar +0.5 altinda (Barlarin ardisik olmasi zorunlu degildir, toplam adet yeterlidir)

NOT: Crossover (tam o anda kesisim) beklenmez. Penceredeki oruntu (toplam adetler) yeterliyse sinyal olusur. Barlar ardisik olmak zorunda degildir.

---

## 4. Emir Tipi

- Giris:  Post-Only Limit Emir (Maker) — en iyi bid/ask'a yerlestirilir
- Chase: Emir dolmazsa ve fiyat %0.15'ten fazla uzaklasirsa iptal edilir
- Cikis:  Limit Emir (Maker) — MOST cizgisine onceden koyulur, price gelince dolar (%0.02 fee)

---

## 5. Risk Yonetimi

### Pozisyon Buyuklugu
  Risk Tutari    = Bakiye x %10
  Stop Mesafesi  = (Giris - MOST line1) / Giris   [min %0.5]
  Pozisyon (USD) = Risk Tutari / Stop Mesafesi
  Kaldirac       = Pozisyon / Bakiye               [max: MAX_LEVERAGE]

Ornek: $100 bakiye, %1 stop -> $10 risk / %0.01 = $1000 pozisyon = 10x

### Trailing Stop
- Baslangic: Giris anindaki MOST line1/line2 degeri
- Her 15 dakikada guncellenir, sadece lehimize hareket eder

---

## 6. Cikis Kosullari

- TRAILING_SL_HIT  : Anlik fiyat trailing stop seviyesine dokundu
- TREND_EXIT       : MOST trendi tersine dondu (K2 veya K1 sinyali)
- EXTERNAL_CLOSE   : Pozisyon borsadan manuel kapatildi

---

## 7. Optimizasyon (c3po.py)

- **Siklik  :** Haftada 4 kez (Pzt 03:00 / Sal 21:00 / Per 15:00 / Cmt 09:00)
- **Yontem  :** Son 750 bar (15M grafik = ~7.8 gun) uzerinde 192 kombinasyon grid search (WFO)
- **Cikti   :** En iyi MOST + IFTStoch parametreleri Supabase guide_table'a yazilir

### Optimizasyon Grid Parametreleri:
- **MOST Periyotlari:** `[8, 13, 21, 34]` (4 deger)
- **MOST Yuzdeleri :** `[0.3%, 0.5%, 0.8%, 1.0%, 1.2%, 1.5%]` (6 deger)
- **Stochastic Boyu:** `[7, 14, 21, 28]` (4 deger)
- **WMA Duzlestirme:** `[5, 9]` (2 deger)
- **Toplam Grid Boyutu:** 4 x 6 x 4 x 2 = **192 kombinasyon**

---

## 8. Koruma Mekanizmalari

- Kara Liste     : Bakiyeyle acılamayacak buyuk lot gerektiren coinler engellenir (jawa.py)
- Tek Islem Modu : /tekislem komutuyla es zamanli islem sayisi 1 ile sinirlanir
- Kesinti Koruma : Tum pozisyon verileri Supabase'de, sunucu cokse bot kaldiği yerden devam eder

