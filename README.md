# Custom Wingman for Wingman AI by ShipBit

We are flattered to present to you our version of a great trading assistant.

## Version: v8

Works with: Wingman AI 2_0_0b2

If you have any feedback, please leave it here: [Discord Channel](https://discord.com/channels/1173573578604687360/1179594417926066196/1185567252184047656)

## What data is this based on?

This wingman is based on a data dump we retrieve from the [uexcorp API](https://uexcorp.space/api.html). As the data is just a collection of ship, location and commodity information, we are able to do all our trading route calculation locally in python. This comes with some benefits, like faster responses and better customizability but does also bring some disadvantages in the form of missing data output like expected trading durations and distance calculation and sometimes does recommend buying more SCU than available. So our trading routes are currently purely based on profit per run. Sometimes its good to ask for multiple routes and select the one you like.

## How to set it up?

1. Download the files from this repository.
2. Copy `wingmen` and `configs` folders into the Wingman Ai configuration directory. (By default on Windows: `%appdata%\Roaming\ShipBit\WingmanAI\2_0_0b2`)
3. Get your own uexcorp API key [here](https://portal.uexcorp.space/terminal) by typing `apikey your_username your@mail.com` at the bottom and follow the written instructions. Or just reuse the api key from the previous version. On first launch you will be asked for it.
4. On the next Wingman AI start, it will take a moment to load all data. Thats it. Enjoy and feel free to leave us feedback [here](https://discord.com/channels/1173573578604687360/1179594417926066196/1185567252184047656) 🙂

## What can I do then?

### Ask for the best trading routes

This gives you the best trading routes for your ship and current location. You can also specify some parameters to get more specific results.

- **ship name** (required, just the name without manufacturer. So "Cutlass Black" for example)
- **current location** Anything like Stanton, Hurston, Yela, Area 18, ...
- target position (Traveling from Hurston to Arccorp? Maybe you should take something with you if your are flying there anyway!)
- budget
- free cargo space (if not given, the ships cargo space is used. But got just 56 SCU free in your Caterpillar? -> give this info then.)
- commodity (Want to trade something specific like gold?)
- illegal commodities (Dont want to trade drugs? Then tell it not to give you these trading routes.)
- count (How many routes do you want to see? Default is 3.)

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