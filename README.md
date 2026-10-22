# Pulpit rynku kawy

Pulpit arabiki i robusty, przelicznik PLN/kg, koszty dostawy i edukacyjny kalkulator scenariuszy na 2027.

## Publikacja

W Settings → Pages → Build and deployment → Source wybierz **GitHub Actions**.
Następnie w Actions uruchom workflow **Aktualizacja danych i publikacja pulpitu** przez **Run workflow**.
Nie potrzeba płatnego API ani własnego serwera.

## Codzienna aktualizacja

GitHub Actions sprawdza dane codziennie o **06:17 UTC** (08:17 latem / 07:17 zimą w Polsce), również przy wyłączonym komputerze. GitHub może opóźniać uruchomienia. Harmonogramy w publicznych repozytoriach mogą zostać wyłączone po 60 dniach bez aktywności; sprawdzaj historię Actions.

- Kawa: publiczna tabela **Futures Price** na https://coffeeboard.gov.in/ — po trzy serie arabiki (USc/lb) i robusty (USD/t). To wtórna publikacja, nie bezpośredni feed ICE. Data sesji jest odczytywana z tabeli, nigdy z daty pobrania.
- Waluty: https://api.nbp.pl/ — USD i EUR, tabela A.
- Historia: `data/market.json`; jedna obserwacja sesji. Zmiana kontraktu przy rolowaniu może powodować skok ceny.
- Błąd źródła: poprzednie wartości zostają, pojawia się komunikat na stronie. Workflow zgłasza niepełną aktualizację po próbie publikacji ostatnich poprawnych danych.
- Tabela może być opóźniona. Odczyty starsze niż cztery dni są oznaczane.

Raporty ICO/USDA, prognozy BMI/Banku Światowego, dane o zapasach oraz parametry logistyki **nie są aktualizowane automatycznie**. Mają własne daty i ograniczenia. Codzienna część obejmuje ceny kontraktów, spread, dostępną krzywą i kursy walut. Brakujące terminy w kalkulatorze są założeniem modelu.

## Uruchomienie i testy

Wymagany Python 3.12+, bez dodatkowych bibliotek.

```sh
python -m unittest discover -s tests -v
python scripts/update_market.py
python -m http.server 8000
```

Otwórz `http://localhost:8000`. `index.html` pobiera `data/market.json` przy otwarciu strony. Wbudowana kopia zapewnia dane początkowe, gdy pobranie się nie powiedzie. Dane wpisane ręcznie i import CSV zapisują się tylko w danej przeglądarce. Dane serwera mają pierwszeństwo w tej samej dacie.

Repozytorium i GitHub Pages są publiczne. Nie umieszczaj w nich haseł, tokenów ani prywatnych ofert handlowych.
