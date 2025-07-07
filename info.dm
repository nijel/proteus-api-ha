# Proteus API Integration

Integrace pro Home Assistant umožňující ovládání a monitorování fotovoltaické soustavy přes Proteus API od Delta Green.

## Co tato integrace umožňuje

- **Sledování flexibility** - dostupnost, aktuální příkazy, zisky z flexibility
- **Monitoring baterie** - režimy, cílový SOC, předpovědi výroby a spotřeby
- **Manuální ovládání** - všechny funkce dostupné v původním rozhraní
- **Automatické režimy** - přepínání mezi automatickým a manuálním řízením

## Instalace

1. Přidejte tuto integraci přes HACS
2. Restartujte Home Assistant
3. Přejděte na Nastavení → Zařízení a služby → Přidat integraci
4. Vyhledejte "Proteus API"
5. Zadejte ID invertoru a session cookie z prohlížeče

## Potřebné údaje

- **ID invertoru**: Najdete v URL (např. z https://proteus.deltagreen.cz/cs/device/inverter/XXX)
- **Session cookie**: Zkopírujte z vývojářských nástrojů prohlížeče (F12)

Session cookie je potřeba obnovit přibližně jednou za měsíc.
