def execute(app_api, params):
    """
    Tato funkce se spustí, když je plugin zavolán.
    Vrátí jednoduchou textovou zprávu.
    """
    print("Ping plugin byl úspěšně spuštěn!")
    return "PONG! Pluginový systém funguje správně."