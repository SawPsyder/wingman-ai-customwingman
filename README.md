# Custom Wingman for Wingman AI by ShipBit

We are flattered to present to you our version of a great trading assistant.

## Version: v9

Works with: Wingman AI 2.1.0b2

If you have any feedback, please leave it here: [Discord Channel](https://discord.com/channels/1173573578604687360/1179594417926066196/1185567252184047656)

## What data is this based on?

This wingman is based on a data dump we retrieve from the [uexcorp API](https://uexcorp.space/api.html). As the data is just a collection of ship, location and commodity information, we are able to do all our trading route calculation locally in python. This comes with some benefits, like faster responses and better customizability but does also bring some disadvantages in the form of missing data output like expected trading durations and distance calculation and sometimes does recommend buying more SCU than available. So our trading routes are currently purely based on profit per run. Sometimes its good to ask for multiple routes and select the one you like.

## How to set it up?

1. Download the latest release: https://github.com/SawPsyder/wingman-ai-customwingman/releases
2. Copy `wingmen` and `configs` folders into the Wingman Ai configuration directory. (By default on Windows: `%appdata%\ShipBit\WingmanAI\2_1_0b2`)
3. Get your own uexcorp API key [here](https://portal.uexcorp.space/terminal) by typing `apikey yourusername your@mail.com` at the bottom and follow the written instructions. Or just reuse the api key from the previous version. On first launch you will be asked for it.
4. On every Wingman AI start after 24h (by default), it will take a moment to load all data. Thats it. Enjoy and feel free to leave us feedback [here](https://discord.com/channels/1173573578604687360/1179594417926066196/1185567252184047656) 🙂

## What can I do then?

### Ask for the best trading routes

This gives you the best trading routes for your ship and current location. You can also specify some parameters to get more specific results.

- **ship name** (required, just the name without manufacturer. So "Cutlass Black" for example)
- **current location** Anything like Stanton, Hurston, Yela, Area 18, ... (Optional, if [Trade Start Mandatory](https://github.com/SawPsyder/wingman-ai-customwingman?tab=readme-ov-file#trade-start-mandatory-true-false) is set to false in the config. Otherwise mandatory.)
- target position (Traveling from Hurston to Arccorp? Maybe you should take something with you if your are flying there anyway!)
- budget
- free cargo space (if not given, the ships cargo space is used. But got just 56 SCU free in your Caterpillar? -> give this info then.)
- commodity (Want to trade something specific like gold?)
- illegal commodities (Dont want to trade drugs? Then tell it not to give you these trading routes.)
- count (How many routes do you want to see? Default is set in the "[Default Trade Route Count](https://github.com/SawPsyder/wingman-ai-customwingman?tab=readme-ov-file#default-trade-route-count-number)" configuration option.)

### Ask for best selling/buying locations

Got something with you or want to buy something? Find the best price!

- **Commodity name** (e.g. Iron)
- ship name
- current location (It will search in your given area. If nothing is found there, it will provide the best location overall.)
- amount (Got 52 SCU of something? Give that information and get estimated selling price of your cargo.)

### Ask for ship information

Gives you some basic information about a ship and where to buy it.

- **ship name** (Just the name without manufacturer. So "Cutlass Black" for example)

### Ask for ship comparison

Gives you some basic information about multiple ships and points out differences.

- **ship names** (Just the name without manufacturer. So "Cutlass Black" and "Freelancer Max" for example. You can also mention a series. Like "Constellation")

### Ask for location information

Gives you some basic information and buy/sell offers of a location.

- **location name** (Anything like Stanton, Hurston, Yela, Area 18, ...)

### Ask for commodity information

Gives you some basic information and prices.

- **commodity name**

### Ask for a price update

Gets the current prices from the API.

## What can I configure?

### Debug Mode (true, false, Extensive)
Set this option to "true" to activate debug mode. All function calls will be printed to the terminal in this mode. This is the default value.
If you want to develop a bit or dive deeper into understanding the responses, you can also set this option to "Extensive".
Set this option to "false" to deactivate debug mode.

### Enable Cache (true, false)
Set this option to "true" to enable caching of the UEX corp API responses. This is recommended, as the API key's quota is very limited.
If you set this option to "false", the Wingman will fetch all data from the UEX corp API on every start.
If you want to update the prices, just tell the Wingman to do so.
If all data should be fetched again, delete the cache file. (wingman_data\uexcorp\cache.json)

### Cache Duration (seconds)
Set this option to the amount of seconds you want to cache the UEX corp API responses.
We recommend a day ("86400"), as the ship, planet, etc. information does not change that often.

### Additional Context (true, false)
Set this option to "true" to automatically attach all possible location, ship and commodity names to the context.
This will slightly improve the behavior of gpt-3.5-turbo-1106 and even more so with gpt-4-1106-preview.
But it comes with a cost, literally. It will cost you more money, as more tokens are used with openai's API.
Approx. additional costs per request due to additional context:
gpt-3.5-turbo-1106: $0.002
gpt-4-1106-preview: $0.02
Default is "false", as the costs are not worth it in our opinion and we built a complete system to avoid the need for this.

### Summarize Routes by Commodity (true, false)
Set this option to "true" to show only one of the most profitable routes for each commodity.
Set this option to "false" to show all routes. This may include multiple routes for the same commodity.
Recommended: "true"

### Trade Start Mandatory (true, false)
Set this option to "true" to make the start location for trade route calculation a mandatory information.
Set this option to "false" to make the start location for trade route calculation a optional information.
If "false" and no start location is given, all tradeports are taken into account.

### Trade Blacklist (JSON string)
Use this to blacklist certain trade ports or commodities or combinations of both.
Default value is '[]', which means no trade ports or commodities are blacklisted.
If we want to add a trade port to the blacklist, we add something like this: `{"tradeport":"Baijini Point"}`
This will blacklist the trade port completely from trade route calculations.
If we want to add a commodity to the blacklist, we add something like this: `{"commodity":"Medical Supplies"}`
This will blacklist the commodity completely from trade route calculations.
If we want to add a combination to the blacklist, we add something like this: `{"tradeport":"Baijini Point", "commodity":"Medical Supplies"}`
This will blacklist this commodity for the given trade port.
If we want to add multiple trade ports or commodities or combinations of both, we add them in a list like this: `[{"tradeport":"Baijini Point", "commodity":"Medical Supplies"}, {"commodity":"Medical Supplies"}, {"tradeport":"Port Tressler"}]`
Or to exclude stuff thats to risky or hard to sell/buy: `[{"commodity":"WiDoW"},{"commodity":"E'tam"},{"commodity":"Neon"},{"commodity":"Altruciatoxin"},{"commodity":"Medical Supplies"}]`
This value is a JSON string, if you have created a list, use a JSON validator like https://jsonlint.com/ to check if the list is valid.

### Default Trade Route Count (number)
Set this option to the amount of trade routes you want to show at default.
You can always tell Wingman AI to show more or less trade routes for one request, if that number is not given, this setting is used.