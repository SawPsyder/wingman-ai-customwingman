from typing import Optional
import math
import json
import difflib
import logging
import itertools
import re
import copy
import os
from datetime import datetime
import requests
from services.secret_keeper import SecretKeeper
from services.printr import Printr
from wingmen.open_ai_wingman import OpenAiWingman

printr = Printr()

class UEXcorpWingman(OpenAiWingman):
    """
    The UEX Corp Wingman class.
    """
    def __init__(
        self,
        name: str,
        config: dict[str, any],
        secret_keeper: SecretKeeper,
        app_root_dir: str,
    ) -> None:
        """
        Initialize the UEX Corp Wingman object.

        Args:
            name (str): The name of the wingman.
            config (dict[str, any]): The configuration settings for the wingman.
            secret_keeper (SecretKeeper): The secret keeper to retrieve secrets from.
            
        Returns:
            None
        """
        super().__init__(
            name=name,
            config=config,
            secret_keeper=secret_keeper,
            app_root_dir=app_root_dir
        )

        self.real_path = os.path.join(self.get_full_file_path("uexcorp"))
        # add folder if not there yet
        if not os.path.exists(self.real_path):
            os.makedirs(self.real_path)
        self.logfile = os.path.join(self.real_path, "uexcorp_error.log")
        self.cachefile = os.path.join(self.real_path, "uexcorp_cache.json")
        logging.basicConfig(filename=self.logfile, level=logging.ERROR)

        self.uexcorp_version = "v6"
        self.uexcorp_api_url = ""
        self.uexcorp_timeout = 5

        self.uexcorp_apikey = None
        self.uexcorp_debug = False
        self.uexcorp_cache = True
        self.uexcorp_cache_duration = 3600
        self.uexcorp_additional_context = False

        self.ships = []
        self.ship_names = []
        self.commodities = []
        self.commodity_names = []
        self.systems = []
        self.system_names = []
        self.tradeports = []
        self.tradeport_names = []
        self.planets = []
        self.planet_names = []
        self.satellites = []
        self.satellite_names = []
        self.cities = []
        self.city_names = []

        self.manufacturers = {}
        self.cache_enabled = True
        self.cache = {
            "function_args": {},
            "search_matches": {},
            "readable_objects": {},
        }

    def _print_debug(self, message: str, is_extensive: bool = False) -> None:
        """
        Prints a debug message if debug mode is enabled.

        Args:
            message (str): The message to be printed.
            is_extensive (bool, optional): Whether the message is extensive. Defaults to False.

        Returns:
            None
        """
        if self.uexcorp_debug is False or (self.cache_enabled is False and self.uexcorp_debug != "Extensive"):
            # this happens in nested function calling. should be spammed into console normally.
            return

        if self.uexcorp_debug == "Extensive" or is_extensive is False:
            printr.print(message, tags=f"{'info' if is_extensive is False else 'warn'}")

    def _get_function_arg_from_cache(
        self, arg_name: str, arg_value: str | int = None
    ) -> dict[str, any]:
        """
        Retrieves a function argument from the cache if available, otherwise returns the provided argument value.

        Args:
            arg_name (str): The name of the function argument.
            arg_value (str | int, optional): The default value for the argument. Defaults to None.

        Returns:
            dict[str, any]: The cached value of the argument if available, otherwise the provided argument value.
        """
        if self.cache_enabled is False:
            return arg_value
        if arg_value is None or (isinstance(arg_value, str) and arg_value.lower() == 'current'):
            if arg_name in self.cache["function_args"]:
                self._print_debug(
                    f"Required function arg '{arg_name}' was not given and got overwritten by cache: {self.cache['function_args'][arg_name]}"
                )
                return self.cache["function_args"][arg_name]
            else:
                return None
        return arg_value

    def _set_function_arg_to_cache(
        self, arg_name: str, arg_value: str | int = None
    ) -> None:
        """
        Sets the value of a function argument to the cache.

        Args:
            arg_name (str): The name of the argument.
            arg_value (str | int, optional): The value of the argument. Defaults to None.
        """
        if self.cache_enabled is False:
            return
        if arg_value is not None:
            if arg_name in self.cache["function_args"]:
                old_value = self.cache["function_args"][arg_name]
            else:
                old_value = "None"
            self._print_debug(
                f"Set function arg '{arg_name}' to cache. Previous value: {old_value} >> New value: {arg_value}",
                True
            )
            self.cache["function_args"][arg_name] = arg_value
        else:
            if arg_name in self.cache["function_args"]:
                self._print_debug(
                    f"Removing function arg '{arg_name}' from cache. Previous value: {self.cache['function_args'][arg_name]}",
                    True
                )
                self.cache["function_args"].pop(arg_name, None)

    def validate(self) -> list[str]:
        """
        Validates the configuration of the UEX Corp Wingman.

        Returns:
            A list of error messages indicating any missing or invalid configuration settings.
        """
        # collect errors from the base class (if any)
        errors: list[str] = super().validate()

        self.uexcorp_apikey = self.secret_keeper.retrieve(
            requester=self.name,
            key="uexcorp",
            friendly_key_name="UEXcorp API key",
            prompt_if_missing=True,
        )
        if not self.uexcorp_apikey:
            errors.append(
                "Missing uexcorp api key. Add the uexcorp api key in you settings. \nYou can get one here: https://uexcorp.space/api.html"
            )

        # add custom errors
        if not self.config.get("uexcorp_api_url"):
            errors.append("Missing 'uexcorp_api_url' in config.yaml")
        if not self.config.get("uexcorp_api_timeout"):
            errors.append("Missing 'uexcorp_api_timeout' in config.yaml")
        if self.config.get("uexcorp_debug") is None:
            errors.append("Missing 'uexcorp_debug' in config.yaml")
        if not self.config.get("uexcorp_cache"):
            errors.append("Missing 'uexcorp_cache' in config.yaml")
        if not self.config.get("uexcorp_cache_duration"):
            errors.append("Missing 'uexcorp_cache_duration' in config.yaml")
        if self.config.get("uexcorp_additional_context") is None:
            errors.append("Missing 'uexcorp_additional_context' in config.yaml")

        return errors

    def _load_data(self, reload: bool = False) -> None:
        """
        Load data for UEX corp wingman.

        Args:
            reload (bool, optional): Whether to reload the data from the source. Defaults to False.
        """

        self.debug = self.config.get("features", {}).get(
            "debug_mode", False
        )
        boo_tradeports_reloaded = False


        save_cache = False
        # if cache is enabled and file is not too old, load from cache
        if self.uexcorp_cache and not reload:
            # check file age
            data = {}
            try:
                with open(self.cachefile, "r", encoding="UTF-8") as f:
                    data = json.load(f)
            except (FileNotFoundError, json.decoder.JSONDecodeError):
                pass

            # check file age
            if (
                data.get("timestamp")
                and data.get("timestamp") + self.uexcorp_cache_duration > self._get_timestamp()
                and data.get("wingman_version") == self.uexcorp_version
            ):
                if data.get("ships"):
                    self.ships = data["ships"]
                if data.get("commodities"):
                    self.commodities = data["commodities"]
                if data.get("systems"):
                    self.systems = data["systems"]
                if data.get("tradeports"):
                    self.tradeports = data["tradeports"]
                    boo_tradeports_reloaded = True
                if data.get("planets"):
                    self.planets = data["planets"]
                if data.get("satellites"):
                    self.satellites = data["satellites"]
                if data.get("cities"):
                    self.cities = data["cities"]
            else:
                save_cache = True

        if not self.ships:
            self.ships = self._fetch_uex_data("ships")
            self.ships = [ship for ship in self.ships if ship["implemented"] == "1"]

        if not self.commodities:
            self.commodities = self._fetch_uex_data("commodities")

        if not self.systems:
            self.systems = self._fetch_uex_data("star_systems")
            self.systems = [
                system for system in self.systems if system["available"] == 1
            ]
            for system in self.systems:
                self.tradeports += self._fetch_uex_data(
                    f"tradeports/system/{system['code']}"
                )
                self.cities += self._fetch_uex_data(f"cities/system/{system['code']}")
                self.satellites += self._fetch_uex_data(
                    f"satellites/system/{system['code']}"
                )
                self.planets += self._fetch_uex_data(f"planets/system/{system['code']}")

            self.tradeports = [
                tradeport
                for tradeport in self.tradeports
                if tradeport["visible"] == "1"
            ]
            boo_tradeports_reloaded = True

            self.planets = [
                planet for planet in self.planets if planet["available"] == 1
            ]

            self.satellites = [
                satellite
                for satellite in self.satellites
                if satellite["available"] == 1
            ]
        else:
            if reload:
                self.tradeports = []
                for system in self.systems:
                    self.tradeports += self._fetch_uex_data(
                        f"tradeports/system/{system['code']}"
                    )

                self.tradeports = [
                    tradeport
                    for tradeport in self.tradeports
                    if tradeport["visible"] == "1"
                ]
                boo_tradeports_reloaded = True
                save_cache = True

        if save_cache:
            data = {
                "timestamp": self._get_timestamp(),
                "wingman_version": self.uexcorp_version,
                "ships": self.ships,
                "commodities": self.commodities,
                "systems": self.systems,
                "tradeports": self.tradeports,
                "planets": self.planets,
                "satellites": self.satellites,
                "cities": self.cities,
            }
            with open(self.cachefile, "w", encoding="UTF-8") as f:
                json.dump(data, f)

        # data manipulation
        # remove planet information from space tradeports
        if boo_tradeports_reloaded is True:
            planet_codes = []
            for planet in self.planets:
                if planet["code"] not in planet_codes:
                    planet_codes.append(planet["code"])

            for tradeport in self.tradeports:
                shorted_name = tradeport["name"].split(" ")[0]
                if (
                    tradeport["space"] == "1"
                    and len(shorted_name.split("-")) == 2
                    and shorted_name.split("-")[0] in planet_codes
                    and re.match(r'^L\d+$', shorted_name.split("-")[1])
                ):
                    tradeport["planet"] = ""
        # remove urls from ships and resolve manufacturer code
        for ship in self.ships:
            ship.pop("store_url", None)
            ship.pop("photos", None)
            ship.pop("brochure_url", None)
            ship.pop("hotsite_url", None)
            ship.pop("video_url", None)
        # remove unavailable cities
        self.cities = [city for city in self.cities if city["available"] == 1]
        # add hull trading option to trade ports
        tradeports_for_hull_trading = [
            "Baijini Point",
            "Everus Harbor",
            "Magnus Gateway",
            "Pyro Gateway",
            "Seraphim Station",
            "Terra Gateway",
            "Port Tressler",
        ]
        for tradeport in self.tradeports:
            tradeport["hull_trading"] = tradeport["name"] in tradeports_for_hull_trading
        # add hull trading option to ships
        ships_for_hull_trading = ["Hull C"]
        for ship in self.ships:
            ship["hull_trading"] = ship["name"] in ships_for_hull_trading

    def prepare(self) -> None:
        """
        Prepares the wingman for execution by initializing necessary variables and loading data.

        This method retrieves configuration values, sets up API URL and timeout, and loads data
        such as ship names, commodity names, system names, tradeport names, city names,
        satellite names and planet names.
        It also adds additional context information for function parameters.

        Returns:
            None
        """
        # here validate() already ran, so we can safely access the config

        self.uexcorp_api_url = self.config.get("uexcorp_api_url")
        self.uexcorp_timeout = self.config.get("uexcorp_timeout")
        self.uexcorp_debug = self.config.get("uexcorp_debug")
        self.uexcorp_cache = self.config.get("uexcorp_cache")
        self.uexcorp_cache_duration = self.config.get("uexcorp_cache_duration")
        self.uexcorp_additional_context = self.config.get("uexcorp_additional_context")

        self.manufacturers = {
            "AEGS": "Aegis Dynamics",
            "ANVL": "Anvil Aerospace",
            "AOPO": "Aopoa",
            "ARGO": "ARGO Astronautics",
            "BANU": "Banu",
            "CNOU": "Consolidated Outland",
            "CRUS": "Crusader Industries",
            "DRAK": "Drake Interplanetary",
            "ESPR": "Esperia",
            "GATA": "Gatac",
            "GRIN": "Greycat Industrial",
            "KRIG": "Kruger Intergalactic",
            "MIRA": "Mirai",
            "MISC": "Musashi Industrial & Starflight Concern",
            "ORIG": "Origin Jumpworks",
            "RSIN": "Roberts Space Industries",
            "TMBL": "Tumbril Land Systems",
            "VNDL": "Vanduul",
        }

        self.start_execution_benchmark()
        self._load_data()

        additional_context = []

        self.ship_names = [
            self._format_ship_name(ship)
            for ship in self.ships
            if ship["implemented"] == "1"
        ]
        additional_context.append(
            'Possible values for function parameter "shipName". If none is explicitly given by player, use "None": '
            + ", ".join(self.ship_names)
        )

        self.commodity_names = [
            self._format_commodity_name(commodity) for commodity in self.commodities
        ]
        additional_context.append(
            'Possible values for function parameter "commodityName": '
            + ", ".join(self.commodity_names)
        )

        self.system_names = [
            self._format_system_name(system) for system in self.systems
        ]

        self.tradeport_names = [
            self._format_tradeport_name(tradeport) for tradeport in self.tradeports
        ]

        self.city_names = [self._format_city_name(city) for city in self.cities]

        self.satellite_names = [
            self._format_satellite_name(satellite) for satellite in self.satellites
        ]

        self.planet_names = [
            self._format_planet_name(planet) for planet in self.planets
        ]

        additional_context.append(
            'Possible values for function parameters "positionStartName", "positionEndName", "currentPositionName" and "locationName": '
            + ", ".join(
                self.system_names
                + self.tradeport_names
                + self.city_names
                + self.satellite_names
                + self.planet_names
            )
        )
        # additional_context.append("Do not (never) translate any properties when giving them to the player. They must stay untouched.")
        # additional_context.append("But do always try to translate the values the player gives you, if they doesnt match initially.")

        if self.uexcorp_additional_context:
            self._add_context("\n".join(additional_context))
        self._add_context("\nOnly give functions parameters that were previously clearly provided by a request. Never assume any values, not the current ship, not the location, not the available money, nothing! Always send a None-value instead.")
        self._add_context("\nIf you are not using one of the definied functions, dont give any trading recommendations.")
        self._add_context("\nIf you execute a function that requires a commodity name, make sure to always provide the name in english, not in german or any other language.")

    def _add_context(self, content: str):
        """
        Adds additional context to the first message content,
        that represents the context given to open ai.

        Args:
            content (str): The additional context to be added.

        Returns:
            None
        """
        # TODO: CLEAN THIS UP AFTER IT IS IMPLEMENTED BY SHIPBIT
        self.messages[0]["content"] += "\n" + content

    def _get_timestamp(self) -> int:
        """
        Get the current timestamp as an integer.

        Returns:
            int: The current timestamp.
        """
        return int(datetime.now().timestamp())

    def _find_closest_match(self, search, lst):
        """
        Finds the closest match to a given string in a list.
        Or returns an exact match if found.
        If it is not an exact match, OpenAI is used to find the closest match.

        Args:
            search (str): The search to find a match for.
            lst (list): The list of strings to search for a match.

        Returns:
            str or None: The closest match found in the list, or None if no match is found.
        """
        if search is None:
            return None

        self._print_debug(f"Searching for closest match to '{search}' in list.", True)

        if search in lst:
            self._print_debug(f"Found exact match to '{search}' in list.", True)
            return search

        # create checksum of provided list and search term
        checksum = f"{len(lst)}--{lst[0]}--{search}".replace(" ", "")
        if checksum in self.cache["search_matches"]:
            self._print_debug(f"Found closest match to '{search}' in cache.", True)
            return self.cache["search_matches"][checksum]

        # make a list of possible matches
        closest_matches = []
        closest_matches = difflib.get_close_matches(search, lst, n=10, cutoff=0.2)
        if len(search) < 3:
            # find all matches, that contain the search term
            for item in lst:
                if search.lower() in item.lower():
                    closest_matches.append(item)
        self._print_debug(f"Making a list for closest matches for search term '{search}': {', '.join(closest_matches)}", True)

        # dumb matches
        if len(closest_matches) == 0:
            self._print_debug(f"No closest match found for '{search}' in list. Returning None.", True)
            return None
        # if len(closest_matches) == 1:
        #     self._print_debug(f"Found only one closest match to '{search}' in list: '{closest_matches[0]}'", True)
        #     return closest_matches[0]

        # openai matches
        response = self.openai.ask(
            messages=[
                {
                    "content": f"""
                        I'll give you just a string value.
                        You will figure out, what value in this list represents this value best: {', '.join(closest_matches)}
                        Keep in mind that the given string value can be misspelled or has missing words as it has its origin in a speach to text process.
                        You must only return the value of the closest match to the given value from the defined list, nothing else.
                        For example if "Hercules A2" is given and the list contains of "A2, C2, M2", you will return "A2" as string.
                        Or if "C2" is given and the list contais of "A2 Herculas Star Lifter, C2 Monter Truck, M2 Extreme cool ship", you will return "C2 Monter Truck" as string.
                        On longer search terms, prefer the exact match, if it is in the list.
                        The response must not contain anything else, than the exact value of the closest match from the list.
                        If you can't find a match, return 'None'. Do never return the given search value.
                    """,
                    "role": "system",
                },
                {
                    "content": search,
                    "role": "user",
                },
            ],
            model="gpt-3.5-turbo-1106",
        )
        answer = response.choices[0].message.content
        if answer == "None":
            self._print_debug(f"OpenAI says this is the closest match: '{answer}'. Returning None.", True)
            self.cache["search_matches"][checksum] = None
            return None

        if answer not in closest_matches:
            self._print_debug(f"OpenAI says this is the closest match: '{answer}'. But it is not in the list of possible matches. Returning None.", True)
            self.cache["search_matches"][checksum] = None
            return None

        self._print_debug(f"OpenAI says this is the closest match: '{answer}'.", True)
        self._add_context(f"\nAlways say '{answer}' instead of '{search}'.") # Say the correct stuff, not the rubbish that was understood.
        self.cache["search_matches"][checksum] = answer
        return answer

    def _get_header(self):
        """
        Returns the header dictionary containing the API key.
        Used for API requests.

        Returns:
            dict: The header dictionary with the API key.
        """
        key = self.uexcorp_apikey
        return {"api_key": key}

    def _fetch_uex_data(
        self, endpoint: str, params: Optional[dict[str, any]] = None
    ) -> list[dict[str, any]]:
        """
        Fetches data from the specified endpoint.

        Args:
            endpoint (str): The API endpoint to fetch data from.
            params (Optional[dict[str, any]]): Optional parameters to include in the request.

        Returns:
            list[dict[str, any]]: The fetched data as a list of dictionaries.
        """
        url = f"{self.uexcorp_api_url}/{endpoint}"

        response = requests.get(
            url, params=params, timeout=self.uexcorp_timeout, headers=self._get_header()
        )
        response.raise_for_status()
        if self.debug:
            self.print_execution_time(reset_timer=True)

        if response.json()["status"] != "ok":
            Printr.err_print(f"Error while retrieving data from {url}")
            return []

        return response.json()["data"]

    def _format_ship_name(self, ship: dict[str, any]) -> str:
        """
        Formats the name of a ship.
        This represents a list of names that can be used by the player.
        So if you like to use manufacturer names + ship names, do it here.

        Args:
            ship (dict[str, any]): The ship dictionary containing the ship details.

        Returns:
            str: The formatted ship name.
        """
        return ship["name"]

    def _format_tradeport_name(self, tradeport: dict[str, any]) -> str:
        """
        Formats the name of a tradeport.

        Args:
            tradeport (dict[str, any]): The tradeport dictionary containing the name.

        Returns:
            str: The formatted tradeport name.
        """
        return tradeport["name"]

    def _format_city_name(self, city: dict[str, any]) -> str:
        """
        Formats the name of a city.

        Args:
            city (dict[str, any]): A dictionary representing a city.

        Returns:
            str: The formatted name of the city.
        """
        return city["name"]

    def _format_planet_name(self, planet: dict[str, any]) -> str:
        """
        Formats the name of a planet.

        Args:
            planet (dict[str, any]): A dictionary representing a planet.

        Returns:
            str: The formatted name of the planet.
        """
        return planet["name"]

    def _format_satellite_name(self, satellite: dict[str, any]) -> str:
        """
        Formats the name of a satellite.

        Args:
            satellite (dict[str, any]): The satellite dictionary.

        Returns:
            str: The formatted satellite name.
        """
        return satellite["name"]

    def _format_system_name(self, system: dict[str, any]) -> str:
        """
        Formats the name of a system.

        Args:
            system (dict[str, any]): The system dictionary containing the name.

        Returns:
            str: The formatted system name.
        """
        return system["name"]

    def _format_commodity_name(self, commodity: dict[str, any]) -> str:
        """
        Formats the name of a commodity.

        Args:
            commodity (dict[str, any]): The commodity dictionary.

        Returns:
            str: The formatted commodity name.
        """
        return commodity["name"]

    async def _execute_command_by_function_call(
        self, function_name: str, function_args: dict[str, any]
    ) -> tuple[str, str]:
        """
        Executes a command by calling the specified function with the given arguments.

        Args:
            function_name (str): The name of the function to be called.
            function_args (dict[str, any]): The arguments to be passed to the function.

        Returns:
            tuple[str, str]: A tuple containing the function response and instant response.
        """
        (
            function_response,
            instant_response,
        ) = await super()._execute_command_by_function_call(
            function_name, function_args
        )

        # use try catch to catch errors in custom functions
        try:
            if function_name == "get_best_trading_route":
                function_response = self._get_best_trading_route(**function_args)
            if function_name == "get_best_location_to_sell_to":
                function_response = self._get_best_location_to_sell_to(**function_args)
            if function_name == "get_multiple_best_locations_to_sell_to":
                function_response = self._get_multiple_best_locations_to_sell_to(**function_args)
            if function_name == "get_best_location_to_buy_from":
                function_response = self._get_best_location_to_buy_from(**function_args)
            if function_name == "get_multiple_best_locations_to_buy_from":
                function_response = self._get_multiple_best_locations_to_buy_from(**function_args)
            if function_name == "get_location_information":
                function_response = self._get_location_information(**function_args)
            if function_name == "get_ship_information":
                function_response = self._get_ship_information(**function_args)
            if function_name == "get_commodity_information":
                function_response = self._get_commodity_information(**function_args)
            if function_name == "reload_current_commodity_prices":
                function_response = self._reload_current_commodity_prices()
            if function_name == "get_multiple_best_trading_routes":
                function_response = self._get_multiple_best_trading_routes(**function_args)
            if function_name == "show_cached_function_values":
                function_response = self._show_cached_function_values()
        except Exception as e:
            logging.error(e, exc_info=True)
            file_object = open(self.logfile, 'a', encoding="UTF-8")
            file_object.write("========================================================================================\n")
            file_object.write(f"Above error while executing custom function: _{function_name}\n")
            file_object.write(f"With parameters: {function_args}\n")
            file_object.write(f"On date: {datetime.now()}\n")
            file_object.write(f"Version: {self.uexcorp_version}\n")
            file_object.write("========================================================================================\n")
            file_object.close()
            self._print_debug(f"Error while executing custom function: {function_name}\nCheck log file for more details.")
            function_response = f"Error while executing custom function: {function_name}"
            function_response += "\nTell user there seems to be an error in the code. And you must say that it should be report to the 'uexcorp wingman developers'."

        return function_response, instant_response

    def _build_tools(self) -> list[dict[str, any]]:
        """
        Builds the toolset for execution.
        Add your own function calls here and they will be available in the chatbot.

        Returns:
            list[dict[str, any]]: The list of tools.
        """
        tools = super()._build_tools()
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "get_best_trading_route",
                    "description": "Finds the best trade route for a given spaceship and position.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "shipName": {"type": "string"},
                            "positionStartName": {"type": "string"},
                            "moneyToSpend": {"type": "number"},
                            "positionEndName": {"type": "string"},
                            "freeCargoSpace": {"type": "number"},
                            "commodityName": {"type": "string"},
                            "illegalCommoditesAllowed": {"type": "boolean"},
                        },
                        # "required": ["shipName", "positionStartName"],
                        # "optional": ["moneyToSpend", "freeCargoSpace", "positionEndName", "commodityName", "illegalCommoditesAllowed"],
                    },
                },
            },
        )
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "get_multiple_best_trading_routes",
                    "description": "Finds all possible commodity trade options and gives back a selection of the best options. If an alternative route is searched for, execute this function.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "shipName": {"type": "string"},
                            "positionStartName": {"type": "string"},
                            "moneyToSpend": {"type": "number"},
                            "positionEndName": {"type": "string"},
                            "freeCargoSpace": {"type": "number"},
                            "commodityName": {"type": "string"},
                            "illegalCommoditesAllowed": {"type": "boolean"},
                            "maximalNumberOfRoutes": {"type": "number"},
                        },
                        # "required": ["shipName", "positionStartName"],
                        # "optional": ["moneyToSpend", "freeCargoSpace", "positionEndName", "commodityName", "illegalCommoditesAllowed", "maximalNumberOfRoutes"],
                    },
                },
            },
        )
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "get_best_location_to_sell_to",
                    "description": "Finds the best location at what the player can sell cargo at.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "commodityName": {"type": "string"},
                            "shipName": {"type": "string"},
                            "positionName": {"type": "string"},
                            "commodityAmount": {"type": "number"},
                        },
                        # "required": ["commodityName"],
                        # "optional": ["shipName", "positionName", "commodityAmount"],
                    },
                },
            },
        )
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "get_multiple_best_locations_to_sell_to",
                    "description": "Finds the best locations at what the player can sell cargo at. If an alternative sell location is searched for, execute this function.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "commodityName": {"type": "string"},
                            "shipName": {"type": "string"},
                            "positionName": {"type": "string"},
                            "commodityAmount": {"type": "number"},
                            "maximalNumberOfLocations": {"type": "number"},
                        },
                        # "required": ["commodityName"],
                        # "optional": ["shipName", "positionName", "commodityAmount", "maximalNumberOfLocations"],
                    },
                },
            },
        )
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "get_best_location_to_buy_from",
                    "description": "Finds the best location at what the player can buy cargo at. Only give positionName if the player specifically wanted to filter for it.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "commodityName": {"type": "string"},
                            "shipName": {"type": "string"},
                            "positionName": {"type": "string"},
                            "commodityAmount": {"type": "number"},
                        },
                        # "required": ["commodityName"],
                        # "optional": ["shipName", "positionName", "commodityAmount"],
                    },
                },
            },
        )
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "get_multiple_best_locations_to_buy_from",
                    "description": "Finds the best locations at what the player can buy cargo at. If an alternative buy location is searched for, execute this function. Only give positionName if the player specifically wanted to filter for it.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "commodityName": {"type": "string"},
                            "shipName": {"type": "string"},
                            "positionName": {"type": "string"},
                            "commodityAmount": {"type": "number"},
                            "maximalNumberOfLocations": {"type": "number"},
                        },
                        # "required": ["commodityName"],
                        # "optional": ["shipName", "positionName", "commodityAmount", "maximalNumberOfLocations"],
                    },
                },
            },
        )
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "get_location_information",
                    "description": "Gives information and commodity prices of this location. Execute this if the player asks for all buy or sell options for a specific location.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "locationName": {"type": "string"},
                        },
                        # "required": ["locationName"],
                    },
                },
            },
        )
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "get_ship_information",
                    "description": "Gives information about the given ship. If a player asks to rent something or buy a ship, this function needs to be executed.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "shipName": {"type": "string"},
                        },
                        # "required": ["shipName"],
                    },
                },
            },
        )
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "get_commodity_information",
                    "description": "Gives information about the given commodity. If a player asks for information about a commodity, this function needs to be executed.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "commodityName": {"type": "string"},
                        },
                        # "required": ["commodityName"],
                    },
                },
            },
        )
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "reload_current_commodity_prices",
                    "description": "Reloads the current commodity prices from UEX corp.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            },
        )
        if self.uexcorp_debug == "Extensive":
            tools.append(
            {
                "type": "function",
                "function": {
                    "name": "show_cached_function_values",
                    "description": "Prints the cached function's argument values to the console.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            },
        )
        return tools

    def _show_cached_function_values(self) -> str:
        """
        Prints the cached function's argument values to the console.

        Returns:
            str: A message indicating that the cached function's argument values have been printed to the console.
        """
        if self.uexcorp_debug:
            self._print_debug("Called custom function _show_cached_function_values")
            self._print_debug(self.cache["function_args"])
            return "Please check the console for the cached function's argument values."
        return ""

    def _reload_current_commodity_prices(self) -> str:
        """
        Reloads the current commodity prices from UEX corp.

        Returns:
            str: A message indicating that the current commodity prices have been reloaded.
        """
        self._print_debug("Called custom function _reload_current_commodity_prices")
        self._load_data(reload=True)
        # clear cached data
        for key in self.cache:
            self.cache[key] = {}

        self._print_debug("Reloaded current commodity prices from UEX corp.", True)
        return "Reloaded current commodity prices from UEX corp."

    def _get_commodity_information(self, commodityName: str = None) -> str:
        """
        Retrieves information about a given commodity.

        Args:
            commodityName (str, optional): The name of the commodity. Defaults to None.

        Returns:
            str: The information about the commodity in JSON format, or an error message if the commodity is not found.
        """
        self._print_debug("Called custom function _get_commodity_information")
        self._print_debug(f"Parameters: Commodity: {commodityName}")

        commodityName = self._get_function_arg_from_cache(
            "commodityName", commodityName
        )

        if commodityName is None:
            self._print_debug("No commodity given. Ask for a commodity.", True)
            return "No commodity given. Ask for a commodity."

        misunderstood = []
        if (
            commodityName is not None
            and self._find_closest_match(commodityName, self.commodity_names) is None
        ):
            misunderstood.append(f"Commodity: {commodityName}")
        else:
            commodityName = self._find_closest_match(commodityName, self.commodity_names)
            # commodity name not set to cache, as this is likely not about the current commodity
            # self._set_function_arg_to_cache("commodityName", commodityName)

        self._print_debug(f"Interpreted Parameters: Commodity: {commodityName}")

        if len(misunderstood) > 0:
            self._print_debug(
                "These given parameters do not exist in game. Exactly ask for clarification of these values: "
                + ", ".join(misunderstood),
                True
            )
            return "These given parameters do not exist in game. Exactly ask for clarification of these values: " + ", ".join(
                misunderstood
            )

        commodity = self._get_commodity_by_name(commodityName)
        if commodity is not None:
            self._print_debug(self._get_converted_commodity_for_output(commodity), True)
            return json.dumps(self._get_converted_commodity_for_output(commodity))

    def _get_ship_information(self, shipName: str = None) -> str:
        """
        Retrieves information about a specific ship.

        Args:
            shipName (str, optional): The name of the ship. Defaults to None.

        Returns:
            str: The ship information or an error message.

        """
        self._print_debug("Called custom function _get_ship_information")
        self._print_debug(f"Parameters: Ship: {shipName}")

        shipName = self._get_function_arg_from_cache(
            "shipName", shipName
        )

        if shipName is None:
            self._print_debug("No ship given. Ask for a ship. Dont say sorry.", True)
            return "No ship given. Ask for a ship. Dont say sorry."

        misunderstood = []
        if (
            shipName is not None
            and self._find_closest_match(shipName, self.ship_names) is None
        ):
            misunderstood.append(f"Ship: {shipName}")
        else:
            shipName = self._find_closest_match(shipName, self.ship_names)
            # ship name not set, as this is likely not about the current ship
            # self._set_function_arg_to_cache("shipName", shipName)

        self._print_debug(f"Interpreted Parameters: Ship: {shipName}")

        if len(misunderstood) > 0:
            self._print_debug(
                "These given parameters do not exist in game. Exactly ask for clarification of these values: "
                + ", ".join(misunderstood),
                True
            )
            return "These given parameters do not exist in game. Exactly ask for clarification of these values: " + ", ".join(
                misunderstood
            )

        ship = self._get_ship_by_name(shipName)
        if ship is not None:
            self._print_debug(self._get_converted_ship_for_output(ship), True)
            return json.dumps(self._get_converted_ship_for_output(ship))

    def _get_location_information(self, locationName: str = None) -> str:
        """
        Retrieves information about a given location.

        Args:
            locationName (str, optional): The name of the location. Defaults to None.

        Returns:
            str: The information about the location in JSON format, or an error message if the location is not found.
        """
        self._print_debug("Called custom function _get_location_information")
        self._print_debug(f"Parameters: Location: {locationName}")

        locationName = self._get_function_arg_from_cache(
            "locationName", locationName
        )

        if locationName is None:
            self._print_debug("No location given. Ask for a location.", True)
            return "No location given. Ask for a location."

        misunderstood = []
        if (
            locationName is not None
            and self._find_closest_match(
                locationName,
                self.tradeport_names
                + self.city_names
                + self.satellite_names
                + self.planet_names
                + self.system_names,
            )
            is None
        ):
            misunderstood.append(f"Location: {locationName}")
        else:
            locationName = self._find_closest_match(
                locationName,
                self.tradeport_names
                + self.city_names
                + self.satellite_names
                + self.planet_names
                + self.system_names,
            )
            # location name not set, as this is likely not about the current location
            # self._set_function_arg_to_cache("locationName", locationName)

        self._print_debug(f"Interpreted Parameters: Location: {locationName}")

        if len(misunderstood) > 0:
            self._print_debug(
                "These given parameters do not exist in game. Exactly ask for clarification of these values: "
                + ", ".join(misunderstood),
                True
            )
            return "These given parameters do not exist in game. Exactly ask for clarification of these values: " + ", ".join(
                misunderstood
            )

        # get a clone of the data
        tradeport = self._get_tradeport_by_name(locationName)
        if tradeport is not None:
            self._print_debug(self._get_converted_tradeport_for_output(tradeport), True)
            return json.dumps(self._get_converted_tradeport_for_output(tradeport))
        city = self._get_city_by_name(locationName)
        if city is not None:
            self._print_debug(self._get_converted_city_for_ouput(city), True)
            return json.dumps(self._get_converted_city_for_ouput(city))
        satellite = self._get_satellite_by_name(locationName)
        if satellite is not None:
            self._print_debug(self._get_converted_satellite_for_ouput(satellite), True)
            return json.dumps(self._get_converted_satellite_for_ouput(satellite))
        planet = self._get_planet_by_name(locationName)
        if planet is not None:
            self._print_debug(self._get_converted_planet_for_ouput(planet), True)
            return json.dumps(self._get_converted_planet_for_ouput(planet))
        system = self._get_system_by_name(locationName)
        if system is not None:
            self._print_debug(self._get_converted_system_for_ouput(system), True)
            return json.dumps(self._get_converted_system_for_ouput(system))

    def _get_converted_tradeport_for_output(self, tradeport: dict[str, any]) -> dict[str, any]:
        """
        Converts a tradeport dictionary to a dictionary that can be used as output.

        Args:
            tradeport (dict[str, any]): The tradeport dictionary to be converted.

        Returns:
            dict[str, any]: The converted tradeport dictionary.
        """
        checksum = f"tradeport--{tradeport['code']}"
        if checksum in self.cache["readable_objects"]:
            return self.cache["readable_objects"][checksum]

        tradeport = copy.deepcopy(tradeport)
        deletable_keys = [
            "code",
            "name_short",
            "space",
            "visible",
            "prices",
            "date_modified",
            "date_added",
        ]
        tradeport["type"] = "Tradeport"
        tradeport["system"] = self._get_system_name_by_code(tradeport["system"])
        tradeport["planet"] = self._get_planet_name_by_code(tradeport["planet"])
        tradeport["city"] = self._get_city_name_by_code(tradeport["city"])
        tradeport["satellite"] = self._get_satellite_name_by_code(tradeport["satellite"])
        if tradeport["hull_trading"] is True:
            tradeport["hull_trading"] = "Trading with MISC Hull C is possible."
        else:
            tradeport["hull_trading"] = "Trading with MISC Hull C is not possible."

        buyable_commodities = []
        sellable_commodities = []
        for commodity_code, data in tradeport["prices"].items():
            if data["operation"] == "buy":
                buyable_commodities.append(f"{data['name']} for {data['price_buy']} aUEC per SCU")
            if data["operation"] == "sell":
                sellable_commodities.append(f"{data['name']} for {data['price_sell']} aUEC per SCU")

        if len(buyable_commodities) > 0:
            tradeport["buyable_commodities"] = ", ".join(buyable_commodities)
        if len(sellable_commodities) > 0:
            tradeport["sellable_commodities"] = ", ".join(sellable_commodities)

        if not tradeport["system"]:
            deletable_keys.append("system")
        if not tradeport["planet"]:
            deletable_keys.append("planet")
        if not tradeport["city"]:
            deletable_keys.append("city")
        if not tradeport["satellite"]:
            deletable_keys.append("satellite")

        for key in deletable_keys:
            tradeport.pop(key, None)

        self.cache["readable_objects"][checksum] = tradeport
        return tradeport

    def _get_converted_city_for_ouput(self, city: dict[str, any]) -> dict[str, any]:
        """
        Converts a city dictionary to a dictionary that can be used as output.

        Args:
            city (dict[str, any]): The city dictionary to be converted.

        Returns:
            dict[str, any]: The converted city dictionary.
        """
        checksum = f"city--{city['code']}"
        if checksum in self.cache["readable_objects"]:
            return self.cache["readable_objects"][checksum]

        city = copy.deepcopy(city)
        deletable_keys = [
            "code",
            "available",
            "date_added",
            "date_modified",
        ]
        city["type"] = "City"
        city["system"] = self._get_system_name_by_code(city["system"])
        city["planet"] = self._get_planet_name_by_code(city["planet"])
        tradeports = self._get_tradeports_by_positionname(city["name"], True)
        if len(tradeports) > 0:
            city["options_to_trade"] = ", ".join([self._format_tradeport_name(tradeport) for tradeport in tradeports])

        for key in deletable_keys:
            city.pop(key, None)

        self.cache["readable_objects"][checksum] = city
        return city

    def _get_converted_satellite_for_ouput(self, satellite: dict[str, any]) -> dict[str, any]:
        """
        Converts a satellite dictionary to a dictionary that can be used as output.

        Args:
            satellite (dict[str, any]): The satellite dictionary to be converted.

        Returns:
            dict[str, any]: The converted satellite dictionary.
        """
        checksum = f"satellite--{satellite['code']}"
        if checksum in self.cache["readable_objects"]:
            return self.cache["readable_objects"][checksum]

        satellite = copy.deepcopy(satellite)
        deletable_keys = [
            "code",
            "available",
            "date_added",
            "date_modified",
        ]
        satellite["type"] = "Satellite"
        satellite["system"] = self._get_system_name_by_code(satellite["system"])
        satellite["planet"] = self._get_planet_name_by_code(satellite["planet"])
        tradeports = self._get_tradeports_by_positionname(satellite["name"], True)
        if len(tradeports) > 0:
            satellite["options_to_trade"] = ", ".join([self._format_tradeport_name(tradeport) for tradeport in tradeports])

        for key in deletable_keys:
            satellite.pop(key, None)

        self.cache["readable_objects"][checksum] = satellite
        return satellite

    def _get_converted_planet_for_ouput(self, planet: dict[str, any]) -> dict[str, any]:
        """
        Converts a planet dictionary to a dictionary that can be used as output.

        Args:
            planet (dict[str, any]): The planet dictionary to be converted.

        Returns:
            dict[str, any]: The converted planet dictionary.
        """
        checksum = f"planet--{planet['code']}"
        if checksum in self.cache["readable_objects"]:
            return self.cache["readable_objects"][checksum]

        planet = copy.deepcopy(planet)
        deletable_keys = [
            "code",
            "available",
            "date_added",
            "date_modified",
        ]
        planet["type"] = "Planet"
        planet["system"] = self._get_system_name_by_code(planet["system"])
        tradeports = self._get_tradeports_by_positionname(planet["name"], True)
        if len(tradeports) > 0:
            planet["options_to_trade"] = ", ".join([self._format_tradeport_name(tradeport) for tradeport in tradeports])
        satellites = self._get_satellites_by_planetcode(planet["code"])
        if len(satellites) > 0:
            planet["satellites"] = ", ".join([self._format_satellite_name(satellite) for satellite in satellites])
        cities = self._get_cities_by_planetcode(planet["code"])
        if len(cities) > 0:
            planet["cities"] = ", ".join([self._format_city_name(city) for city in cities])

        for key in deletable_keys:
            planet.pop(key, None)

        self.cache["readable_objects"][checksum] = planet
        return planet

    def _get_converted_system_for_ouput(self, system: dict[str, any]) -> dict[str, any]:
        """
        Converts a system dictionary to a dictionary that can be used as output.

        Args:
            system (dict[str, any]): The system dictionary to be converted.

        Returns:
            dict[str, any]: The converted system dictionary.
        """
        checksum = f"system--{system['code']}"
        if checksum in self.cache["readable_objects"]:
            return self.cache["readable_objects"][checksum]

        system = copy.deepcopy(system)
        deletable_keys = [
            "code",
            "available",
            "default",
            "date_added",
            "date_modified",
        ]
        system["type"] = "System"
        tradeports = self._get_tradeports_by_positionname(system["name"], True)
        if len(tradeports) > 0:
            system["options_to_trade"] = ", ".join([self._format_tradeport_name(tradeport) for tradeport in tradeports])
        planets = self._get_planets_by_systemcode(system["code"])
        if len(planets) > 0:
            system["planets"] = ", ".join([self._format_planet_name(planet) for planet in planets])

        for key in deletable_keys:
            system.pop(key, None)

        self.cache["readable_objects"][checksum] = system
        return system

    def _get_converted_ship_for_output(self, ship: dict[str, any]) -> dict[str, any]:
        """
        Converts a ship dictionary to a dictionary that can be used as output.

        Args:
            ship (dict[str, any]): The ship dictionary to be converted.

        Returns:
            dict[str, any]: The converted ship dictionary.
        """
        checksum = f"ship--{ship['code']}"
        if checksum in self.cache["readable_objects"]:
            return self.cache["readable_objects"][checksum]

        ship = copy.deepcopy(ship)
        deletable_keys = [
            "code",
            "loaner",
            "scu",
            "implemented",
            "mining",
            "stealth",
            "price",
            "price_warbond",
            "price_pkg",
            "sell_active",
            "sell_active_warbond",
            "sell_active_pkg",
            "stock_qt_speed",
            "showdown_winner",
            "date_added",
            "date_modified",
            "hull_trading",
        ]
        ship["type"] = "Ship"
        ship["manufacturer"] = (
            self.manufacturers[ship["manufacturer"]]
            if ship["manufacturer"] in self.manufacturers
            else ship["manufacturer"]
        )
        ship["cargo"] = f"{ship['scu']} SCU"
        ship["price_USD"] = f"{ship['price']}"
        if not ship["buy_at"]:
            ship["buy_at"] = "This ship cannot be bought."
        else:
            temp = ship["buy_at"]
            ship["buy_at"] = []
            for position in temp:
                ship["buy_at"].append(self._get_converted_rent_and_buy_option_for_output(position))
        if not ship["rent_at"]:
            ship["rent_at"] = "This ship cannot be rented."
        else:
            temp = ship["rent_at"]
            ship["rent_at"] = []
            for position in temp:
                ship["rent_at"].append(self._get_converted_rent_and_buy_option_for_output(position))
        if ship["hull_trading"] is True:
            ship["trading_info"] = "This ship can only trade on suitable space stations with a cargo deck."

        for key in deletable_keys:
            ship.pop(key, None)

        self.cache["readable_objects"][checksum] = ship
        return ship

    def _get_converted_rent_and_buy_option_for_output(
        self, position: dict[str, any]
    ) -> dict[str, any]:
        """
        Converts a rent/buy option dictionary to a dictionary that can be used as output.

        Args:
            position (dict[str, any]): The rent/buy option dictionary to be converted.

        Returns:
            dict[str, any]: The converted rent/buy option dictionary.
        """
        position = copy.deepcopy(position)
        if not position["tradeport"]:
            if not position["system"]:
                position.pop("system", None)
            else:
                position["system"] = position["system_name"]
            if not position["planet"]:
                position.pop("planet", None)
            else:
                position["planet"] = position["planet_name"]
            if not position["satellite"]:
                position.pop("satellite", None)
            else:
                position["satellite"] = position["satellite_name"]
            if not position["city"]:
                position.pop("city", None)
            else:
                position["city"] = position["city_name"]
            if not position["store"]:
                position.pop("store", None)
            else:
                position["store"] = position["store_name"]
            position.pop("tradeport", None)
        else:
            tradeport = self._get_tradeport_by_code(position["tradeport"])
            position["tradeport"] = self._format_tradeport_name(tradeport)
            system_name = self._get_system_name_by_code(tradeport["system"])
            if system_name:
                position["system"] = self._get_system_name_by_code(tradeport["system"])
            else:
                position.pop("system", None)
            planet_name = self._get_planet_name_by_code(tradeport["planet"])
            if planet_name:
                position["planet"] = planet_name
            else:
                position.pop("planet", None)
            city_name = self._get_city_name_by_code(tradeport["city"])
            if city_name:
                position["city"] = city_name
            else:
                position.pop("city", None)
            satellite_name = self._get_satellite_name_by_code(tradeport["satellite"])
            if satellite_name:
                position["satellite"] = satellite_name
            else:
                position.pop("satellite", None)
            position["store"] = "Refinery" # TODO: remove this when refinery is implemented
        position["price"] = f"{position['price']} aUEC"

        position.pop("tradeport_name", None)
        position.pop("system_name", None)
        position.pop("planet_name", None)
        position.pop("satellite_name", None)
        position.pop("tradeport_name", None)
        position.pop("city_name", None)
        position.pop("store_name", None)
        position.pop("date_added", None)
        position.pop("date_modified", None)

        return position

    def _get_converted_commodity_for_output(self, commodity: dict[str, any]) -> dict[str, any]:
        """
        Converts a commodity dictionary to a dictionary that can be used as output.

        Args:
            commodity (dict[str, any]): The commodity dictionary to be converted.

        Returns:
            dict[str, any]: The converted commodity dictionary.
        """
        checksum = f"commodity--{commodity['code']}"
        if checksum in self.cache["readable_objects"]:
            return self.cache["readable_objects"][checksum]

        commodity = copy.deepcopy(commodity)
        deletable_keys = [
            "code",
            "tradable",
            "trade_price_buy",
            "trade_price_sell",
            "temporary",
            "restricted",
            "raw",
            "available",
            "date_added",
            "date_modified",
        ]
        if commodity["trade_price_buy"] == 0:
            commodity["buyable"] = "No"
            deletable_keys.append("trade_price_buy")
        else:
            commodity["buyable"] = f"Yes ({int(commodity['trade_price_buy'])} aUEC per SCU)"
        if commodity["trade_price_sell"] == 0:
            commodity["sellable"] = "No"
            deletable_keys.append("trade_price_sell")
        else:
            commodity["sellable"] = f"Yes ({int(commodity['trade_price_sell'])} aUEC per SCU)"
        if commodity["minable"] == '0':
            commodity["minable"] = "No"
        else:
            commodity["minable"] = "Yes"
        if commodity["harvestable"] == '0':
            commodity["harvestable"] = "No"
        else:
            commodity["harvestable"] = "Yes"
        if commodity["illegal"] == '0':
            commodity["illegal"] = "No"
        else:
            commodity["illegal"] = "Yes, stay away from ship scanns to avoid fines and crimestat."

        for key in deletable_keys:
            commodity.pop(key, None)

        self.cache["readable_objects"][checksum] = commodity
        return commodity

    def _get_multiple_best_locations_to_sell_to(
        self,
        commodityName: str = None,
        shipName: str = None,
        positionName: str = None,
        commodityAmount: int = 1,
        maximalNumberOfLocations: int = 3,
    ) -> str:
        """
        Finds the best selling locations for a given commodity and position.

        Args:
            commodityName (str, optional): The name of the commodity. Defaults to None.
            shipName (str, optional): The name of the ship. Defaults to None.
            positionName (str, optional): The name of the current position. Defaults to None.
            commodityAmount (int, optional): The amount of the commodity. Defaults to 1.
            maximalNumberOfLocations (int, optional): The maximal number of locations to be returned. Defaults to 3.

        Returns:
            str: A string containing information about the best selling location(s) and sell prices.
        """
        self._print_debug("Called custom function _get_multiple_best_location_to_sell_to")
        self._print_debug(
            f"Given Parameters: Commodity: {commodityName}, Ship Name: {shipName}, Current Position: {positionName}, Amount: {commodityAmount}, Maximal Number of Locations: {maximalNumberOfLocations}"
        )

        commodityName = self._get_function_arg_from_cache("commodityName", commodityName)
        shipName = self._get_function_arg_from_cache("shipName", shipName)

        if commodityName is None:
            self._print_debug("No commodity given. Ask for a commodity.", True)
            return "No commodity given. Ask for a commodity."

        misunderstood = []
        if (
            commodityName is not None
            and self._find_closest_match(commodityName, self.commodity_names) is None
        ):
            misunderstood.append(f"Commodity: {commodityName}")
        else:
            commodityName = self._find_closest_match(
                commodityName, self.commodity_names
            )
            self._set_function_arg_to_cache("commodityName", commodityName)
        if (
            shipName is not None
            and self._find_closest_match(shipName, self.ship_names) is None
        ):
            misunderstood.append(f"Ship: {shipName}")
        else:
            shipName = self._find_closest_match(shipName, self.ship_names)
            self._set_function_arg_to_cache("shipName", shipName)
        if (
            positionName is not None
            and self._find_closest_match(
                positionName,
                self.tradeport_names
                + self.city_names
                + self.satellite_names
                + self.planet_names
                + self.system_names,
            )
            is None
        ):
            misunderstood.append(f"Current Position: {positionName}")
        else:
            positionName = self._find_closest_match(
                positionName,
                self.tradeport_names
                + self.city_names
                + self.satellite_names
                + self.planet_names
                + self.system_names,
            )
            self._set_function_arg_to_cache("locationName", positionName)
        self._print_debug(
            f"Interpreted Parameters: Commodity: {commodityName}, Ship Name: {shipName}, Position: {positionName}, Amount: {commodityAmount}"
        )

        if len(misunderstood) > 0:
            self._print_debug(
                "These given parameters do not exist in game. Exactly ask for clarification of these values: "
                + ", ".join(misunderstood),
                True
            )
            return "These given parameters do not exist in game. Exactly ask for clarification of these values: " + ", ".join(
                misunderstood
            )

        if positionName is None:
            tradeports = self.tradeports
        else:
            tradeports = self._get_tradeports_by_positionname(positionName)
        commodity = self._get_commodity_by_name(commodityName)
        ship = self._get_ship_by_name(shipName)
        if commodityAmount is None:
            amount = 1
        else:
            amount = int(commodityAmount)
        if amount < 1:
            amount = 1
        maximal_number_of_locations = int(maximalNumberOfLocations)
        if maximal_number_of_locations < 1:
            maximal_number_of_locations = 3

        selloptions = {}
        for tradeport in tradeports:
            sellprice = self._get_data_location_sellprice(tradeport, commodity, ship, amount)
            if sellprice is None:
                continue
            if sellprice not in selloptions:
                selloptions[sellprice] = []
            selloptions[sellprice].append(tradeport)

        selloptions = dict(sorted(selloptions.items(), reverse=True))
        selloptions = dict(itertools.islice(selloptions.items(), maximal_number_of_locations))

        messages = []
        messages.append(f"Here are the best {len(selloptions)} locations to sell {amount} SCU {commodityName}:")
        for sellprice, tradeports in selloptions.items():
            messages.append(f"{sellprice} aUEC:")
            for tradeport in tradeports:
                messages.append(self._get_tradeport_route_description(tradeport))

        self._print_debug("\n".join(messages), True)
        return "\n".join(messages)

    def _get_multiple_best_locations_to_buy_from(
        self,
        commodityName: str = None,
        shipName: str = None,
        positionName: str = None,
        commodityAmount: int = 1,
        maximalNumberOfLocations: int = 3,
    ) -> str:
        """
        Finds the best buying locations for a given commodity and position.

        Args:
            commodityName (str, optional): The name of the commodity. Defaults to None.
            shipName (str, optional): The name of the ship. Defaults to None.
            positionName (str, optional): The name of the current position. Defaults to None.
            commodityAmount (int, optional): The amount of the commodity. Defaults to 1.
            maximalNumberOfLocations (int, optional): The maximal number of locations to be returned. Defaults to 3.

        Returns:
            str: A string containing information about the best buying location(s) and buy prices.
        """
        self._print_debug("Called custom function _get_multiple_best_location_to_buy_from")
        self._print_debug(
            f"Given Parameters: Commodity: {commodityName}, Ship Name: {shipName}, Current Position: {positionName}, Amount: {commodityAmount}, Maximal Number of Locations: {maximalNumberOfLocations}"
        )

        commodityName = self._get_function_arg_from_cache("commodityName", commodityName)
        shipName = self._get_function_arg_from_cache("shipName", shipName)

        if commodityName is None:
            self._print_debug("No commodity given. Ask for a commodity.", True)
            return "No commodity given. Ask for a commodity."

        misunderstood = []
        if (
            commodityName is not None
            and self._find_closest_match(commodityName, self.commodity_names) is None
        ):
            misunderstood.append(f"Commodity: {commodityName}")
        else:
            commodityName = self._find_closest_match(
                commodityName, self.commodity_names
            )
            self._set_function_arg_to_cache("commodityName", commodityName)
        if (
            shipName is not None
            and self._find_closest_match(shipName, self.ship_names) is None
        ):
            misunderstood.append(f"Ship: {shipName}")
        else:
            shipName = self._find_closest_match(shipName, self.ship_names)
            self._set_function_arg_to_cache("shipName", shipName)
        if (
            positionName is not None
            and self._find_closest_match(
                positionName,
                self.tradeport_names
                + self.city_names
                + self.satellite_names
                + self.planet_names
                + self.system_names,
            )
            is None
        ):
            misunderstood.append(f"Current Position: {positionName}")
        else:
            positionName = self._find_closest_match(
                positionName,
                self.tradeport_names
                + self.city_names
                + self.satellite_names
                + self.planet_names
                + self.system_names,
            )
            self._set_function_arg_to_cache("locationName", positionName)
        self._print_debug(
            f"Interpreted Parameters: Commodity: {commodityName}, Ship Name: {shipName}, Position: {positionName}, Amount: {commodityAmount}, Maximal Number of Locations: {maximalNumberOfLocations}"
        )

        if len(misunderstood) > 0:
            self._print_debug(
                "These given parameters do not exist in game. Exactly ask for clarification of these values: "
                + ", ".join(misunderstood),
                True
            )
            return "These given parameters do not exist in game. Exactly ask for clarification of these values: " + ", ".join(
                misunderstood
            )

        if positionName is None:
            tradeports = self.tradeports
        else:
            tradeports = self._get_tradeports_by_positionname(positionName)
        commodity = self._get_commodity_by_name(commodityName)
        ship = self._get_ship_by_name(shipName)
        if commodityAmount is None:
            amount = 1
        else:
            amount = int(commodityAmount)
        if amount < 1:
            amount = 1
        maximal_number_of_locations = int(maximalNumberOfLocations)
        if maximal_number_of_locations < 1:
            maximal_number_of_locations = 3

        buyoptions = {}
        for tradeport in tradeports:
            buyprice = self._get_data_location_buyprice(tradeport, commodity, ship, amount)
            if buyprice is None:
                continue
            if buyprice not in buyoptions:
                buyoptions[buyprice] = []
            buyoptions[buyprice].append(tradeport)

        buyoptions = dict(sorted(buyoptions.items(), reverse=False))
        buyoptions = dict(itertools.islice(buyoptions.items(), maximal_number_of_locations))

        messages = []
        messages.append(f"Here are the best {len(buyoptions)} locations to buy {amount} SCU {commodityName}:")
        for buyprice, tradeports in buyoptions.items():
            messages.append(f"{buyprice} aUEC:")
            for tradeport in tradeports:
                messages.append(self._get_tradeport_route_description(tradeport))

        self._print_debug("\n".join(messages), True)
        return "\n".join(messages)

    def _get_data_location_sellprice(self, tradeport, commodity, ship=None, amount=1):
        if ship is not None and ship["hull_trading"] is True and tradeport["hull_trading"] is False:
            return None

        for commodity_code, price in tradeport["prices"].items():
            if commodity_code == commodity["code"] and price["operation"] == "sell":
                return price["price_sell"] * amount
        return None

    def _get_data_location_buyprice(self, tradeport, commodity, ship=None, amount=1):
        if ship is not None and ship["hull_trading"] is True and tradeport["hull_trading"] is False:
            return None

        for commodity_code, price in tradeport["prices"].items():
            if commodity_code == commodity["code"] and price["operation"] == "buy":
                return price["price_buy"] * amount
        return None

    def _get_best_location_to_sell_to(
        self,
        commodityName: str = None,
        shipName: str = None,
        positionName: str = None,
        commodityAmount: float = 1,
    ) -> str:
        """
        Finds the best selling location for a given commodity and position.

        Args:
            commodityName (str, optional): The name of the commodity. Defaults to None.
            shipName (str, optional): The name of the ship. Defaults to None.
            positionName (str, optional): The name of the current position. Defaults to None.
            commodityAmount (float, optional): The amount of the commodity. Defaults to 1.

        Returns:
            str: A string containing information about the best selling location(s) and sell prices.
        """
        self._print_debug("Called custom function _get_best_location_to_sell_to")
        self._print_debug(
            f"Given Parameters: Commodity: {commodityName}, Ship Name: {shipName}, Current Position: {positionName}, Amount: {commodityAmount}"
        )
        return self._get_multiple_best_locations_to_sell_to(commodityName, shipName, positionName, commodityAmount, 1)

    def _get_best_location_to_buy_from(
        self,
        commodityName: str = None,
        shipName: str = None,
        positionName: str = None,
        commodityAmount: float = 1,
    ) -> str:
        """
        Finds the best selling location for a given commodity and position.

        Args:
            commodityName (str, optional): The name of the commodity. Defaults to None.
            shipName (str, optional): The name of the ship. Defaults to None.
            positionName (str, optional): The name of the current position. Defaults to None.
            commodityAmount (float, optional): The amount of the commodity. Defaults to 1.

        Returns:
            str: A string containing information about the best selling location(s) and sell prices.
        """
        self._print_debug("Called custom function _get_best_location_to_buy_from")
        self._print_debug(
            f"Given Parameters: Commodity: {commodityName}, Ship Name: {shipName}, Current Position: {positionName}, Amount: {commodityAmount}"
        )
        return self._get_multiple_best_locations_to_buy_from(commodityName, shipName, positionName, commodityAmount, 1)

    def _get_multiple_best_trading_routes(
        self,
        shipName: str = None,
        moneyToSpend: float = None,
        positionStartName: str = None,
        freeCargoSpace: float = None,
        positionEndName: str = None,
        commodityName: str = None,
        illegalCommoditesAllowed: bool = None,
        maximalNumberOfRoutes: int = 2,
    ) -> str:
        """
        Finds multiple best trading routes based on the given parameters.

        Args:
            shipName (str, optional): The name of the ship. Defaults to None.
            moneyToSpend (float, optional): The amount of money to spend. Defaults to None.
            positionStartName (str, optional): The name of the starting position. Defaults to None.
            freeCargoSpace (float, optional): The amount of free cargo space. Defaults to None.
            positionEndName (str, optional): The name of the ending position. Defaults to None.
            commodityName (str, optional): The name of the commodity. Defaults to None.
            illegalCommoditesAllowed (bool, optional): Flag indicating whether illegal commodities are allowed. Defaults to True.
            maximalNumberOfRoutes (int, optional): The maximum number of routes to return. Defaults to 2.

        Returns:
            str: A string representation of the trading routes found.
        """
        self._print_debug(
            "Called custom function _get_multiple_best_trading_routes"
        )
        self._print_debug(
            f"Parameters: Ship: {shipName}, Position Start: {positionStartName}, Position End: {positionEndName}, Commodity Name: {commodityName}, Money: {moneyToSpend} aUEC, FreeCargoSpace: {freeCargoSpace} SCU, Maximal Number of Routes: {maximalNumberOfRoutes}, Illegal Allowed: {illegalCommoditesAllowed}"
        )

        shipName = self._get_function_arg_from_cache("shipName", shipName)
        # positionStartName = self._get_function_arg_from_cache("locationName", positionStartName) # not working so well as this is will change frequently
        illegalCommoditesAllowed = self._get_function_arg_from_cache("illegalCommoditesAllowed", illegalCommoditesAllowed)
        if illegalCommoditesAllowed is None:
            illegalCommoditesAllowed = True
        else:
            self._set_function_arg_to_cache("illegalCommoditesAllowed", illegalCommoditesAllowed)

        if shipName is None:
            self._print_debug("No ship given. Ask for a ship. Dont say sorry.", True)
            return "No ship given. Ask for a ship. Dont say sorry."

        if positionStartName is None:
            self._print_debug(
                "No start position given. Ask for a start position. (Station, Planet, Satellite, City or System)",
                True
            )
            return "No start position given. Ask for a start position. (Station, Planet, Satellite, City or System)"

        if moneyToSpend is not None and int(moneyToSpend) < 1:
            moneyToSpend = None
        if freeCargoSpace is not None and int(freeCargoSpace) < 1:
            freeCargoSpace = None

        misunderstood = []
        if (
            shipName is not None
            and self._find_closest_match(shipName, self.ship_names) is None
        ):
            misunderstood.append(f"Ship: {shipName}")
        else:
            shipName = self._find_closest_match(shipName, self.ship_names)
            self._set_function_arg_to_cache("shipName", shipName)
        if (
            positionStartName is not None
            and self._find_closest_match(
                positionStartName,
                self.tradeport_names
                + self.city_names
                + self.satellite_names
                + self.planet_names
                + self.system_names,
            )
            is None
        ):
            misunderstood.append(f"Position Start: {positionStartName}")
        else:
            positionStartName = self._find_closest_match(
                positionStartName,
                self.tradeport_names
                + self.city_names
                + self.satellite_names
                + self.planet_names
                + self.system_names,
            )
            self._set_function_arg_to_cache("locationName", positionStartName)
        if (
            positionEndName is not None
            and self._find_closest_match(
                positionEndName,
                self.tradeport_names
                + self.city_names
                + self.satellite_names
                + self.planet_names
                + self.system_names,
            )
            is None
        ):
            misunderstood.append(f"Position End: {positionEndName}")
        else:
            positionEndName = self._find_closest_match(
                positionEndName,
                self.tradeport_names
                + self.city_names
                + self.satellite_names
                + self.planet_names
                + self.system_names,
            )
            self._set_function_arg_to_cache("locationNameTarget", positionEndName)
        if (
            commodityName is not None
            and self._find_closest_match(commodityName, self.commodity_names) is None
        ):
            misunderstood.append(f"Commodity: {commodityName}")
        else:
            commodityName = self._find_closest_match(
                commodityName, self.commodity_names
            )
            self._set_function_arg_to_cache("commodityName", commodityName)

        self._print_debug(
            f"Interpreted Parameters: Ship: {shipName}, Position Start: {positionStartName}, Position End: {positionEndName}, Commodity Name: {commodityName}, Money: {moneyToSpend} aUEC, FreeCargoSpace: {freeCargoSpace} SCU, Maximal Number of Routes: {maximalNumberOfRoutes}, Illegal Allowed: {illegalCommoditesAllowed}"
        )

        self._set_function_arg_to_cache("money", moneyToSpend)

        if len(misunderstood) > 0:
            self._print_debug(
                "These given parameters do not exist in game. Exactly ask for clarification of these values: "
                + ", ".join(misunderstood),
                True
            )
            return "These given parameters do not exist in game. Exactly ask for clarification of these values: " + ", ".join(
                misunderstood
            )

        trading_routes = []
        if commodityName is None:
            for commodity in self.commodity_names:
                self.cache_enabled = False
                trading_route_new = self._get_best_trading_route(
                    shipName,
                    moneyToSpend,
                    positionStartName,
                    freeCargoSpace,
                    positionEndName,
                    commodity,
                    illegalCommoditesAllowed,
                )
                self.cache_enabled = True
                self._print_debug(trading_route_new, True)
                if trading_route_new.startswith("{"):
                    trading_route_new = json.loads(trading_route_new)
                    trading_routes.append(trading_route_new)
        else:
            commodity = self._get_commodity_by_name(commodityName)
            if positionStartName is not None:
                start_tradeports = self._get_tradeports_by_positionname(
                    positionStartName
                )
            else:
                start_tradeports = self.tradeports
            if positionEndName is not None:
                end_tradeports = self._get_tradeports_by_positionname(positionEndName)
            else:
                end_tradeports = self.tradeports

            for start_tradeport in start_tradeports:
                if (
                    commodity["code"] in start_tradeport["prices"]
                    and start_tradeport["prices"][commodity["code"]]["operation"]
                    == "buy"
                ):
                    for end_tradeport in end_tradeports:
                        if (
                            commodity["code"] in end_tradeport["prices"]
                            and end_tradeport["prices"][commodity["code"]]["operation"]
                            == "sell"
                        ):
                            self.cache_enabled = False
                            trading_route_new = self._get_best_trading_route(
                                shipName,
                                moneyToSpend,
                                self._format_tradeport_name(start_tradeport),
                                freeCargoSpace,
                                self._format_tradeport_name(end_tradeport),
                                commodityName,
                                illegalCommoditesAllowed,
                            )
                            self.cache_enabled = True
                            self._print_debug(trading_route_new, True)
                            if trading_route_new.startswith("{"):
                                trading_route_new = json.loads(trading_route_new)
                                trading_routes.append(trading_route_new)

        # sort the trading routes by proft descending
        trading_routes = sorted(
            trading_routes, key=lambda k: int(k["profit"].split(" ")[0]), reverse=True
        )

        # remove all but the first maximalNumberOfRoutes routes
        if len(trading_routes) > maximalNumberOfRoutes:
            trading_routes = trading_routes[:maximalNumberOfRoutes]

        if len(trading_routes) > 0:
            additional_answer = ""
            if len(trading_routes) == maximalNumberOfRoutes:
                additional_answer = " Tell the player their might be more routes with lower profit, but they are not shown to keep it short. "
            if len(trading_routes) < maximalNumberOfRoutes:
                additional_answer = f" Tell the player there are only {len(trading_routes)} with different commodities available. "

            self._print_debug(
                "List possible commodites with just their profit and only give further information on request (e.g. 86 SCU Astantine for a profit of 45.567 aUEC)."
                + additional_answer
                + "JSON: "
                + json.dumps(trading_routes),
                True
            )
            return (
                "List possible commodites with just their profit and only give further information on request (e.g. 86 SCU Astantine for a profit of 45.567 aUEC)."
                + additional_answer
                + "JSON: "
                + json.dumps(trading_routes)
            )
        else:
            self._print_debug("No trading routes found.", True)
            return "No trading routes found."

    def _get_best_trading_route(
        self,
        shipName: str = None,
        moneyToSpend: float = None,
        positionStartName: str = None,
        freeCargoSpace: float = None,
        positionEndName: str = None,
        commodityName: str = None,
        illegalCommoditesAllowed: bool = None,
    ) -> str:
        """
        Finds the best trading route based on the given parameters.

        Args:
            shipName (str, optional): The name of the ship. Defaults to None.
            moneyToSpend (float, optional): The amount of money to spend. Defaults to None.
            positionStartName (str, optional): The name of the starting position. Defaults to None.
            freeCargoSpace (float, optional): The amount of free cargo space. Defaults to None.
            positionEndName (str, optional): The name of the ending position. Defaults to None.
            commodityName (str, optional): The name of the commodity. Defaults to None.
            illegalCommoditesAllowed (bool, optional): Whether illegal commodities are allowed. Defaults to True.

        Returns:
            str: A JSON string representing the best trading route.

        Raises:
            None

        """
        self._print_debug("Called custom function _get_best_trading_route")
        self._print_debug(
            f"Parameters: Ship: {shipName}, Position Start: {positionStartName}, Position End: {positionEndName},  Money: {moneyToSpend} aUEC, FreeCargoSpace: {freeCargoSpace} SCU, Commodity: {commodityName}, Illegal Allowed: {illegalCommoditesAllowed}"
        )

        shipName = self._get_function_arg_from_cache("shipName", shipName)
        # positionStartName = self._get_function_arg_from_cache("locationName", positionStartName) # not working so well as this is will change frequently
        illegalCommoditesAllowed = self._get_function_arg_from_cache("illegalCommoditesAllowed", illegalCommoditesAllowed)
        if illegalCommoditesAllowed is None:
            illegalCommoditesAllowed = True
        else :
            self._set_function_arg_to_cache("illegalCommoditesAllowed", illegalCommoditesAllowed)

        if shipName is None:
            self._print_debug("No ship given. Ask for a ship. Dont say sorry.", True)
            return "No ship given. Ask for a ship. Dont say sorry."

        if moneyToSpend is not None and int(moneyToSpend) < 1:
            moneyToSpend = None
        if freeCargoSpace is not None and int(freeCargoSpace) < 1:
            freeCargoSpace = None

        misunderstood = []
        if (
            shipName is not None
            and self._find_closest_match(shipName, self.ship_names) is None
        ):
            misunderstood.append(f"Ship: {shipName}")
        else:
            shipName = self._find_closest_match(shipName, self.ship_names)
            self._set_function_arg_to_cache("shipName", shipName)
        if (
            positionStartName is not None
            and self._find_closest_match(
                positionStartName,
                self.tradeport_names
                + self.city_names
                + self.satellite_names
                + self.planet_names
                + self.system_names,
            )
            is None
        ):
            misunderstood.append(f"Position Start: {positionStartName}")
        else:
            positionStartName = self._find_closest_match(
                positionStartName,
                self.tradeport_names
                + self.city_names
                + self.satellite_names
                + self.planet_names
                + self.system_names,
            )
            self._set_function_arg_to_cache("locationName", positionStartName)
        if (
            positionEndName is not None
            and self._find_closest_match(
                positionEndName,
                self.tradeport_names
                + self.city_names
                + self.satellite_names
                + self.planet_names
                + self.system_names,
            )
            is None
        ):
            misunderstood.append(f"Position End: {positionEndName}")
        else:
            positionEndName = self._find_closest_match(
                positionEndName,
                self.tradeport_names
                + self.city_names
                + self.satellite_names
                + self.planet_names
                + self.system_names,
            )
            self._set_function_arg_to_cache("locationNameTarget", positionEndName)
        if (
            commodityName is not None
            and self._find_closest_match(commodityName, self.commodity_names) is None
        ):
            misunderstood.append(f"Commodity: {commodityName}")
        else:
            commodityName = self._find_closest_match(
                commodityName, self.commodity_names
            )
            self._set_function_arg_to_cache("commodityName", commodityName)

        self._set_function_arg_to_cache("money", moneyToSpend)

        self._print_debug(
            f"Interpreted Parameters: Ship: {shipName}, Position Start: {positionStartName}, Position End: {positionEndName},  Money: {moneyToSpend} aUEC, FreeCargoSpace: {freeCargoSpace} SCU, Commodity: {commodityName}, Illegal Allowed: {illegalCommoditesAllowed}"
        )

        if len(misunderstood) > 0:
            self._print_debug(
                "These given parameters do not exist in game. Exactly ask for clarification of these values: "
                + ", ".join(misunderstood),
                True
            )
            return "These given parameters do not exist in game. Exactly ask for clarification of these values: " + ", ".join(
                misunderstood
            )

        ship = self._get_ship_by_name(shipName)
        cargo_space = ship["scu"]
        if freeCargoSpace:
            cargo_space = freeCargoSpace
            if freeCargoSpace > ship["scu"]:
                cargo_space = ship["scu"]

        if moneyToSpend is None:
            money = None
        else:
            money = int(moneyToSpend)

        commodity_filter = self._get_commodity_by_name(commodityName)

        start_tradeports = self._get_tradeports_by_positionname(positionStartName)
        if ship["hull_trading"] is True:
            start_tradeports = [
                tradeport
                for tradeport in start_tradeports
                if tradeport["hull_trading"] is True
            ]
        if len(start_tradeports) < 1:
            if ship["hull_trading"] is True:
                self._print_debug(
                    "No valid start position given. Make sure to provide a start point compatible with your ship.",
                    True
                )
                return "No valid start position given. Make sure to provide a start point compatible with your ship."
            self._print_debug(
                "No valid start position given. Try a different position or just name a planet or star system.",
                True
            )
            return "No valid start position given. Try a different position or just name a planet or star system."

        end_tradeports = self._get_tradeports_by_positionname(positionEndName)

        if len(end_tradeports) < 1 and positionEndName is not None:
            self._print_debug("No valid end position given.", True)
            return "No valid end position given."

        if len(end_tradeports) < 1:
            for tradeport in self.tradeports:
                if tradeport["system"] == start_tradeports[0]["system"]:
                    end_tradeports.append(tradeport)

        if positionEndName and len(end_tradeports) == 1 and len(start_tradeports) == 1:
            if end_tradeports[0]["code"] == start_tradeports[0]["code"]:
                self._print_debug("Start and end position are the same.", True)
                return "Start and end position are the same."

        if ship["hull_trading"] is True:
            end_tradeports = [
                tradeport
                for tradeport in end_tradeports
                if "hull_trading" in tradeport and tradeport["hull_trading"] is True
            ]

        if ship is None:
            self._print_debug("Invalid ship given.", True)
            return "Invalid ship given."

        if cargo_space <= 0 or (money is not None and money <= 0):
            self._print_debug("You dont have enough cargo space or money to trade.", True)
            return "You dont have enough cargo space or money to trade."

        best_route = {
            "start": [],
            "end": [],
            "commodity": {},
            "profit": 0,
            "cargo": 0,
            "buy": 0,
            "sell": 0,
        }

        for tradeport_start in start_tradeports:
            commodities = []
            for attr, price in tradeport_start["prices"].items():
                if price["operation"] == "buy" and (
                    commodity_filter is None or commodity_filter["code"] == attr
                ):
                    if illegalCommoditesAllowed is True or price["kind"] != "Drug":
                        price["short_name"] = attr
                        commodities.append(price)

            for tradeport_end in end_tradeports:
                for attr, price in tradeport_end["prices"].items():
                    price["short_name"] = attr
                    for commodity in commodities:
                        if (
                            commodity["short_name"] == price["short_name"]
                            and price["operation"] == "sell"
                            and price["price_sell"] > commodity["price_buy"]
                        ):
                            if money is None:
                                cargo_by_money = cargo_space
                            else:
                                cargo_by_money = math.floor(
                                    money / commodity["price_buy"]
                                )
                            cargo_by_space = cargo_space
                            cargo = min(cargo_by_money, cargo_by_space)
                            if cargo >= 1:
                                profit = round(
                                    cargo
                                    * (price["price_sell"] - commodity["price_buy"])
                                )
                                if profit > best_route["profit"]:
                                    best_route["start"] = [tradeport_start]
                                    best_route["end"] = [tradeport_end]
                                    best_route["commodity"] = price
                                    best_route["profit"] = profit
                                    best_route["cargo"] = cargo
                                    best_route["buy"] = commodity["price_buy"] * cargo
                                    best_route["sell"] = price["price_sell"] * cargo
                                else:
                                    if (
                                        profit == best_route["profit"]
                                        and best_route["commodity"]["short_name"]
                                        == price["short_name"]
                                    ):
                                        if tradeport_start not in best_route["start"]:
                                            best_route["start"].append(tradeport_start)
                                        if tradeport_end not in best_route["end"]:
                                            best_route["end"].append(tradeport_end)

        if len(best_route["start"]) == 0:
            self._print_debug(
                f"No route found for your {shipName} starting from {positionStartName}. Try a different route.",
                True
            )
            return f"No route found for your {shipName} starting from {positionStartName}. Try a different route."

        destinationselection = []
        for tradeport in best_route["end"]:
            destinationselection.append(
                f"({self._get_tradeport_route_description(tradeport)})"
            )
        best_route["end"] = " OR ".join(destinationselection)
        startselection = []
        for tradeport in best_route["start"]:
            startselection.append(
                f"({self._get_tradeport_route_description(tradeport)})"
            )
        best_route["start"] = " OR ".join(startselection)

        best_route["commodity"] = f"{best_route['commodity']['name']}"
        best_route["profit"] = f"{best_route['profit']} aUEC"
        best_route["cargo"] = f"{best_route['cargo']} SCU"
        best_route["buy"] = f"{best_route['buy']} aUEC"
        best_route["sell"] = f"{best_route['sell']} aUEC"

        self._print_debug(best_route, True)
        return json.dumps(best_route)

    def _get_ship_by_name(self, name: str) -> Optional[object]:
        """Finds the ship with the specified name and returns the ship or None.

        Args:
            name (str): The name of the ship to search for.

        Returns:
            Optional[object]: The ship object if found, or None if not found.
        """
        if not name:
            return None
        return next(
            (
                ship
                for ship in self.ships
                if self._format_ship_name(ship).lower() == name.lower()
            ),
            None,
        )

    def _get_tradeport_by_name(self, name: str) -> Optional[object]:
        """Finds the tradeport with the specified name and returns the tradeport or None.

        Args:
            name (str): The name of the tradeport to search for.

        Returns:
            Optional[object]: The tradeport object if found, otherwise None.
        """
        if not name:
            return None
        return next(
            (
                tradeport
                for tradeport in self.tradeports
                if self._format_tradeport_name(tradeport).lower() == name.lower()
            ),
            None,
        )

    def _get_tradeport_by_code(self, code: str) -> Optional[object]:
        """Finds the tradeport with the specified code and returns the tradeport or None.

        Args:
            code (str): The code of the tradeport to search for.

        Returns:
            Optional[object]: The tradeport object if found, otherwise None.
        """
        if not code:
            return None
        return next(
            (
                tradeport
                for tradeport in self.tradeports
                if tradeport["code"].lower() == code.lower()
            ),
            None,
        )

    def _get_planet_by_name(self, name: str) -> Optional[object]:
        """Finds the planet with the specified name and returns the planet or None.

        Args:
            name (str): The name of the planet to search for.

        Returns:
            Optional[object]: The planet object if found, otherwise None.
        """
        if not name:
            return None
        return next(
            (
                planet
                for planet in self.planets
                if self._format_planet_name(planet).lower() == name.lower()
            ),
            None,
        )

    def _get_city_by_name(self, name: str) -> Optional[object]:
        """Finds the city with the specified name and returns the city or None.

        Args:
            name (str): The name of the city to search for.

        Returns:
            Optional[object]: The city object if found, or None if not found.
        """
        if not name:
            return None
        return next(
            (
                city
                for city in self.cities
                if self._format_city_name(city).lower() == name.lower()
            ),
            None,
        )

    def _get_satellite_by_name(self, name: str) -> Optional[object]:
        """Finds the satellite with the specified name and returns the satellite or None.

        Args:
            name (str): The name of the satellite to search for.

        Returns:
            Optional[object]: The satellite object if found, otherwise None.
        """
        if not name:
            return None
        return next(
            (
                satellite
                for satellite in self.satellites
                if self._format_satellite_name(satellite).lower() == name.lower()
            ),
            None,
        )

    def _get_system_by_name(self, name: str) -> Optional[object]:
        """Finds the system with the specified name and returns the system or None.

        Args:
            name (str): The name of the system to search for.

        Returns:
            Optional[object]: The system object if found, otherwise None.
        """
        if not name:
            return None
        return next(
            (
                system
                for system in self.systems
                if self._format_system_name(system).lower() == name.lower()
            ),
            None,
        )

    def _get_commodity_by_name(self, name: str) -> Optional[object]:
        """Finds the commodity with the specified name and returns the commodity or None.

        Args:
            name (str): The name of the commodity to search for.

        Returns:
            Optional[object]: The commodity object if found, otherwise None.
        """
        if not name:
            return None
        return next(
            (
                commodity
                for commodity in self.commodities
                if self._format_commodity_name(commodity).lower() == name.lower()
            ),
            None,
        )

    def _get_tradeport_route_description(self, tradeport: dict[str, any]) -> str:
        """Returns the breadcrums of a tradeport.

        Args:
            tradeport (dict[str, any]): The tradeport information.

        Returns:
            str: The description of the tradeport route.
        """
        route = []
        tradeport = self._get_converted_tradeport_for_output(tradeport)
        if "system" in tradeport:
            route.append(
                f"Star-System: {tradeport['system']}"
            )
        if "planet" in tradeport:
            route.append(
                f"Planet: {tradeport['planet']}"
            )
        if "satellite" in tradeport:
            route.append(
                f"Satellite: {tradeport['satellite']}"
            )
        if "city" in tradeport:
            route.append(f"City: {tradeport['city']}")
        if "name" in tradeport:
            route.append(f"Trade Point: {tradeport['name']}")
        return f"({' >> '.join(route)})"

    def _get_system_name_by_code(self, code: str) -> str:
        """Returns the name of the system with the specified code.

        Args:
            code (str): The code of the system.

        Returns:
            str: The name of the system with the specified code.
        """
        if not code:
            return ""
        return next(
            (
                system["name"]
                for system in self.systems
                if system["code"].lower() == code.lower()
            ),
            "",
        )

    def _get_planet_name_by_code(self, code: str) -> str:
        """Returns the name of the planet with the specified code.

        Args:
            code (str): The code of the planet.

        Returns:
            str: The name of the planet with the specified code.
        """
        if not code:
            return ""
        return next(
            (
                planet["name"]
                for planet in self.planets
                if planet["code"].lower() == code.lower()
            ),
            "",
        )

    def _get_satellite_name_by_code(self, code: str) -> str:
        """Returns the name of the satellite with the specified code.

        Args:
            code (str): The code of the satellite.

        Returns:
            str: The name of the satellite with the specified code.
        """
        if not code:
            return ""
        return next(
            (
                satellite["name"]
                for satellite in self.satellites
                if satellite["code"].lower() == code.lower()
            ),
            "",
        )

    def _get_city_name_by_code(self, code: str) -> str:
        """Returns the name of the city with the specified code.

        Args:
            code (str): The code of the city.

        Returns:
            str: The name of the city with the specified code.
        """
        if not code:
            return ""
        return next(
            (
                city["name"]
                for city in self.cities
                if city["code"].lower() == code.lower()
            ),
            "",
        )

    def _get_commodity_name_by_code(self, code: str) -> str:
        """Returns the name of the commodity with the specified code.

        Args:
            code (str): The code of the commodity.

        Returns:
            str: The name of the commodity with the specified code.
        """
        if not code:
            return ""
        return next(
            (
                commodity["name"]
                for commodity in self.commodities
                if commodity["code"].lower() == code.lower()
            ),
            "",
        )

    def _get_tradeports_by_positionname(self, name: str, direct: bool = False) -> list[dict[str, any]]:
        """Returns all tradeports with the specified position name.

        Args:
            name (str): The position name to search for.

        Returns:
            list[dict[str, any]]: A list of tradeports matching the position name.
        """
        if not name:
            return []
        tradeport = self._get_tradeport_by_name(name)
        city = self._get_city_by_name(name)
        satellite = self._get_satellite_by_name(name)
        planet = self._get_planet_by_name(name)
        system = self._get_system_by_name(name)

        tradeports = []
        if system is not None:
            for tradeport in self.tradeports:
                if tradeport["system"] == system["code"] and (direct is False or not tradeport["planet"]):
                    tradeports.append(tradeport)
        else:
            if planet is not None:
                for tradeport in self.tradeports:
                    if tradeport["planet"] == planet["code"] and (direct is False or not tradeport["satellite"]):
                        tradeports.append(tradeport)
            else:
                if satellite is not None:
                    for tradeport in self.tradeports:
                        if tradeport["satellite"] == satellite["code"]:
                            tradeports.append(tradeport)
                else:
                    if city is not None:
                        for tradeport in self.tradeports:
                            if tradeport["city"] == city["code"]:
                                tradeports.append(tradeport)
                    else:
                        if tradeport is not None:
                            tradeports.append(tradeport)

        return tradeports

    def _get_satellites_by_planetcode(self, code: str) -> list[dict[str, any]]:
        """Returns the satellite with the specified planet code.

        Args:
            code (str): The code of the planet.

        Returns:
            Optional[object]: The satellite object if found, otherwise None.
        """
        if not code:
            return []
        return [
            satellite
            for satellite in self.satellites
            if satellite["planet"].lower() == code.lower()
        ]

    def _get_cities_by_planetcode(self, code: str) -> list[dict[str, any]]:
        """Returns all cities with the specified planet code.

        Args:
            code (str): The code of the planet.

        Returns:
            list[dict[str, any]]: A list of cities matching the planet code.
        """
        if not code:
            return []
        return [
            city
            for city in self.cities
            if city["planet"].lower() == code.lower()
        ]

    def _get_planets_by_systemcode(self, code: str) -> list[dict[str, any]]:
        """Returns all planets with the specified system code.

        Args:
            code (str): The code of the system.

        Returns:
            list[dict[str, any]]: A list of planets matching the system code.
        """
        if not code:
            return []
        return [
            planet
            for planet in self.planets
            if planet["system"].lower() == code.lower()
        ]
