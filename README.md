# Blackjack Pilot 🃏

Modern AI-driven Blackjack Assistant och YOLO11 träningsmiljö med automatisk kortdetektering, Hi-Lo korträkning och realtids Basic Strategy rådgivare.

---

## 📁 Projektstruktur

```text
blackjack-pilot/
├── main.py                     # Huvudapplikation (PySide6 GUI, live screen capture)
├── blackjack_strategy.py       # Basic Strategy motor (hard, soft, pair splits)
├── card_counter.py             # Hi-Lo korträknare & True Count beräkning
├── round_stats.py              # Statistik, vinstfrekvens och rundspårning
├── requirements.txt            # Python-beroenden
├── models/
│   └── yolo11m_blackjack_1280.pt # Tränad YOLO11m modell @ 1280p (97.4% mAP50)
├── dataset/                    # Datasetstruktur för framtida träning
│   ├── data.yaml               # YOLO datasetkonfiguration
│   ├── train/images/ & labels/
│   ├── valid/images/ & labels/
│   └── test/images/ & labels/
└── training/                   # Tränings- & analysverktyg
    ├── train.py                # Träna YOLO11m på 1280p widescreen (GPU optimerad)
    ├── test.py                 # Interaktiv bildgranskning & detekteringstest
    └── video2image.py          # Automatisk frame-extraherare från videor
```

---

## 🚀 Kom igång

### 1. Installera beroenden
```bash
pip install -r requirements.txt
```

### 2. Starta appen
```bash
python main.py
```

### 3. Användning
1. **Välj videofeed**: Klicka på *Markera Videofeed (Bord)* och dra en ruta över ditt blackjack-bord (t.ex. videofönstret eller fullscreen feeden).
2. **Definiera zoner**:
   - Klicka på *Välj Dealer-zon* och markera området där dealerns kort landar.
   - Klicka på *Välj Spelar-zon* och markera området för din box/dina kort.
3. **Spela**: Appen identifierar korten i realtid, visar dealer upcard, din handsumma, Hi-Lo räkning och optimal Basic Strategy åtgärd (Hit, Stand, Double, Split).

---

## 🛠️ Träning & Modellverktyg

### Testa modellen på bilder:
```bash
python training/test.py
```
*(Tryck mellanslag för nästa bild, 'q' för att avsluta)*

### Extrahera bildrutor ur en video:
```bash
python training/video2image.py
```

### Träna en ny modell:
Placera bilder och annoteringar i `dataset/train` och `dataset/valid`, kör sedan:
```bash
python training/train.py
```
*(Vid avslutad träning kopieras bästa vikterna automatiskt till `models/yolo11m_blackjack_1280.pt`)*

