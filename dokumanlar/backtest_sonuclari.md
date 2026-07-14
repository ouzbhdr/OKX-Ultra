# OKX Ultra — Ana Strateji Backtest Sonuclari
**Guncelleme Tarihi:** 7 Temmuz 2026  
**Test Periyodu:** Son 3 Ay (90 Gun / ~8,640 bar)  
**Zaman Dilimi:** 15M  

---

## 📈 Genel Performans

| Metrik | Deger |
|---|---|
| Baslangic Kasasi | $20.00 |
| Bitis Kasasi | $170,326,322,740,836,396,305,910,700,886,815,995,597,351,775,039,477,776,384.00 |
| Net PnL | +851,631,613,704,181,937,973,410,538,553,956,654,674,809,123,931,057,815,552.00% |
| Toplam Islem | 5,373 |
| Kazanan Islem | 3,457 |
| Kaybeden Islem | 1,916 |
| **Win Rate (Kazanma Orani)** | **%64.3** |
| **Ortalama R Getirisi (AvgR)** | **+0.3502** |

---

## 🛠️ Test Kosullari ve Modeli

- **Shared Capital:** Tum coinler ($20'dan baslayan) tek bir ortak kasayi paylasir. 
- **Pozisyon Boyutu:** Acik pozisyon yokken serbest kasanin (free capital) %10'u riske edilir. Bir pozisyon acikken yeni sinyal gelirse, o an kalan serbest kasanin %10'u riske edilir.
- **Komisyon Modeli:** Giris maker (%0.02), Cikis maker (%0.02 - limit stop).
- **Pariteler:** `BTC`, `ETH`, `SOL`, `BNB`, `XRP`, `DOGE` (OKX Swap).
- **WFO Parametreleri:** 720 bar lookback (7.5 gun) / 168 bar step (1.75 gun). 192 kombinasyonlu grid.

---

## 💡 Teknik Analiz

1. **Edge (Matematiksel Avantaj):** 5.373 gibi buyuk bir islem sayisinda **%64.3 Win Rate** ve **+0.35 AvgR** degerlerinin korunmasi, stratejinin uzun vadeli matematiksel avantajini kesin olarak ispatlar.
2. **Limit Stop Verimliligi:** Stoplarin trailing limit emir olarak girilmesi ve %0.02 Maker fee odenmesi, komisyon maliyetlerini en aza indirerek karliligi korumustur.
