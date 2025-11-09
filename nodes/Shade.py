"""Module for the Hunter Douglas PowerView Shade nodes in a Polyglot v3 NodeServer.

This module defines the base Shade class and several subclasses, each representing
a different type of Hunter Douglas PowerView shade with varying capabilities
(e.g., primary, secondary, and tilt controls).

(C) 2025 Stephen Jenkins
"""

# std libraries
from datetime import datetime, timezone
from threading import Thread

# external libraries
import udi_interface

LOGGER = udi_interface.LOGGER


"""
HunterDouglas PowerView G3 url's
"""
URL_DEFAULT_GATEWAY = "powerview-g3.local"
URL_GATEWAY = "http://{g}/gateway"
URL_HOME = "http://{g}/home"
URL_ROOMS = "http://{g}/home/rooms"
URL_ROOM = "http://{g}/home/rooms/{id}"
URL_SHADES = "http://{g}/home/shades/{id}"
URL_SHADES_MOTION = "http://{g}/home/shades/{id}/motion"
URL_SHADES_POSITIONS = "http://{g}/home/shades/positions?ids={id}"
URL_SHADES_STOP = "http://{g}/home/shades/stop?ids={id}"
URL_SCENES = "http://{g}/home/scenes/{id}"
URL_SCENES_ACTIVATE = "http://{g}/home/scenes/{id}/activate"
URL_EVENTS = "http://{g}/home/events"
URL_EVENTS_SCENES = "http://{g}/home/scenes/events"
URL_EVENTS_SHADES = "http://{g}/home/shades/events"


"""
HunterDouglas PowerView G2 url's
from api file: [[https://github.com/sejgit/indigo-powerview/blob/master/PowerView%20API.md]]
"""
URL_G2_HUB = "http://{g}/api/userdata/"
URL_G2_ROOMS = "http://{g}/api/rooms"
URL_G2_ROOM = "http://{g}/api/rooms/{id}"
URL_G2_SHADES = "http://{g}/api/shades"
URL_G2_SHADE = "http://{g}/api/shades/{id}"
URL_G2_SHADE_BATTERY = "http://{g}/api/shades/{id}?updateBatteryLevel=true"
URL_G2_SCENES = "http://{g}/api/scenes"
URL_G2_SCENE = "http://{g}/api/scenes?sceneid={id}"
URL_G2_SCENES_ACTIVATE = "http://{g}/api/scenes?sceneId={id}"
G2_DIVR = 65535


class Shade(udi_interface.Node):
    """Polyglot v3 NodeServer node for a generic Hunter Douglas PowerView Shade.

    This is the base class for all Hunter Douglas PowerView shades. It handles
    positioning, status updates, and commands for a shade. Subclasses are used
    to represent shades with different physical capabilities.

    Attributes:
        id (str): The Polyglot node ID for this shade type.

    Shade Capabilities:
        Type 0 - Bottom Up: Standard roller/screen shades, Duette bottom up.
            Uses the “primary” control type.
        Type 1 - Bottom Up w/ 90° Tilt: Silhouette, Pirouette.
            Uses the “primary” and “tilt” control types.
        Type 2 - Bottom Up w/ 180° Tilt: Silhouette Halo.
            Uses the “primary” and “tilt” control types.
        Type 3 - Vertical (Traversing): Skyline, Duette Vertiglide, Design
            Studio Drapery. Uses the “primary” control type.
        Type 4 - Vertical (Traversing) w/ 180° Tilt: Luminette.
            Uses the “primary” and “tilt” control types.
        Type 5 - Tilt Only 180°: Palm Beach Shutters, Parkland Wood Blinds.
            Uses the “tilt” control type.
        Type 6 - Top Down: Duette Top Down.
            Uses the “primary” control type.
        Type 7 - Top-Down/Bottom-Up: Duette TDBU, Vignette TDBU.
            Uses the “primary” and “secondary” control types.
        Type 8 - Duolite (front and rear shades): Roller Duolite, Vignette
            Duolite, Dual Roller. Uses the “primary” and “secondary” control types.
        Type 9 - Duolite with 90° Tilt: Silhouette Duolite, Silhouette Adeux.
            Uses the “primary,” “secondary,” and “tilt” control types.
        Type 10 - Duolite with 180° Tilt: Silhouette Halo Duolite.
            Uses the “primary,” “secondary,” and “tilt” control types.
    """

    id = "shadeid"

    def __init__(self, poly, primary, address, name, sid):
        """Initializes the Shade node.

        Args:
            poly: The Polyglot interface object.
            primary: The address of the primary controller node.
            address: The address of this shade node.
            name: The name of this shade node.
            sid (str): For TaHoma: deviceURL (e.g., "io://1234-5678-9012/12345678")
                      For PowerView: shade ID (integer)
        """
        super().__init__(poly, primary, address, name)
        self.poly = poly
        self.primary = primary
        self.controller = poly.getNode(self.primary)
        self.address = address
        self.name = name

        # For TaHoma, sid is the deviceURL string
        # For PowerView, it's an integer shade ID
        self.sid = sid
        self.device_url = (
            sid if isinstance(sid, str) and sid.startswith("io://") else None
        )

        self.tiltCapable = [1, 2, 4, 5, 9, 10]
        self.tiltOnly90Capable = [1, 9]

        self.lpfx = f"{address}:{name}"
        self.event_polling_in = False
        self._event_polling_thread = None

        self.poly.subscribe(self.poly.START, self.start, address)
        self.poly.subscribe(self.poly.POLL, self.poll)

    def start(self):
        """Handles the startup sequence for the shade node.

        This method is called after Polyglot has added the node. It sets the
        shade ID driver, waits for the controller to be ready, updates its
        initial data, and starts the event polling loop.
        """
        # For TaHoma, we can't use deviceURL as a driver value (must be numeric)
        # So we'll use a hash or just set to 1 to indicate it's initialized
        if self.device_url:
            # TaHoma device - use hash of deviceURL as numeric ID
            device_id_hash = abs(hash(self.device_url)) % 9999999
            self.setDriver("GV0", device_id_hash, report=True, force=True)
        else:
            # PowerView device - use integer sid
            self.setDriver("GV0", self.sid, report=True, force=True)

        # wait for controller start ready
        self.controller.ready_event.wait()
        self.updateData()

        # start event polling loop
        if not self.event_polling_in:
            self.start_event_polling()

    def poll(self, flag):
        """Handles polling requests from Polyglot.

        This method is called by Polyglot for short polls. It ensures the
        controller is ready and starts the event polling loop if not already running.

        Args:
            flag (str): A string indicating the type of poll ('shortPoll').
        """
        if not self.controller.ready_event:
            LOGGER.error(f"Node not ready yet, exiting {self.lpfx}")
            return

        if "shortPoll" in flag:
            LOGGER.debug(f"shortPoll shade {self.lpfx}")

            # start event polling loop
            if not self.event_polling_in:
                self.start_event_polling()

    def start_event_polling(self):
        """Starts the background thread for polling and processing gateway events.

        This ensures that the event processing loop is running in its own thread,
        consuming events that are queued by the SSE client.
        """
        LOGGER.info(f"start: {self.lpfx}")
        if self._event_polling_thread and self._event_polling_thread.is_alive():
            return  # Already running

        self.controller.stop_sse_client_event.clear()
        self._event_polling_thread = Thread(
            target=self._poll_events,
            name=f"ShadeEventPollingThread{self.sid}",
            daemon=True,
        )
        self._event_polling_thread.start()
        LOGGER.info(f"exit: {self.lpfx}")

    def _poll_events(self):
        """The main loop for processing events from the gateway event queue.

        This method runs in a dedicated thread and continuously processes events
        relevant to this shade, such as 'home' updates and Gen 3 specific events.
        """
        self.event_polling_in = True

        while not self.controller.stop_sse_client_event.is_set():
            # wait for events to process
            gateway_events = self.controller.get_gateway_event()

            # home update event
            # Use next() with a generator expression for efficient lookup
            try:
                home_event = next(
                    (e for e in gateway_events if e.get("evt") == "home"), None
                )
            except Exception as ex:
                LOGGER.error(f"shade {self.sid} home event error: {ex}", exc_info=True)
                home_event = None

            if home_event:
                try:
                    if self.sid in home_event.get("shades", []):
                        LOGGER.debug(f"shade {self.sid} update")
                        if self.updateData():
                            # Directly modify the object reference
                            home_event["shades"].remove(self.sid)
                except (KeyError, ValueError) as ex:
                    LOGGER.error(
                        f"shade event error sid = {self.sid}: {ex}", exc_info=True
                    )

            # process G3 events
            if self.controller.generation == 3:
                try:
                    self._poll_events_for_g3(gateway_events)
                except Exception as ex:
                    LOGGER.error(
                        f"shade:{self.sid}, g3 event error {ex}", exc_info=True
                    )

        self.event_polling_in = False
        LOGGER.info(f"shade:{self.sid} exiting poll events due to controller shutdown")

    def _poll_events_for_g3(self, gateway_events):
        """Processes Gen 3 specific gateway events for the shade.

        This method handles events like 'motion-started', 'motion-stopped',
        'shade-online', 'shade-offline', and 'battery-alert' that are specific
        to Gen 3 gateways.

        Args:
            gateway_events (list[dict]): A list of gateway events to process.
        """
        # handle the G3 events in isoDate order
        try:
            # filter events without isoDate like home
            event_nohome = (e for e in gateway_events if e.get("isoDate") is not None)
            # get most recent isoDate
            event = min(event_nohome, key=lambda x: x["isoDate"], default={})

        except (ValueError, TypeError) as ex:  # Catch specific exceptions
            LOGGER.error(
                f"Error filtering or finding minimum event: {ex}", exc_info=True
            )
            event = {}

        # only process the rest for this particular shade
        if event.get("id") == self.sid:
            # motion-started event
            if event.get("evt") == "motion-started":
                LOGGER.info(f"shade {self.sid} motion-started event")
                self.updatePositions(self.posToPercent(event["targetPositions"]))
                self.setDriver("ST", 1, report=True, force=True)
                self.reportCmd("DON", 2)
                self.controller.remove_gateway_event(event)

            # motion-stopped event
            if event.get("evt") == "motion-stopped":
                LOGGER.info(f"shade {self.sid} motion-stopped event")
                self.updatePositions(self.posToPercent(event["currentPositions"]))
                self.setDriver("ST", 0, report=True, force=True)
                self.reportCmd("DOF", 2)
                # add event for scene active calc
                d = datetime.now(timezone.utc).isoformat().rstrip("+00:00") + "Z"
                e = {"evt": "scene-calc", "isoDate": d, "shadeId": self.sid}
                e["scenes"] = list(self.controller.scenes_map.keys())
                self.controller.append_gateway_event(e)
                self.controller.remove_gateway_event(event)

            # shade-online event
            if event.get("evt") == "shade-online":
                LOGGER.info(f"shade {self.sid} shade-online event")
                self.updatePositions(self.posToPercent(event["currentPositions"]))
                self.controller.remove_gateway_event(event)

            # # shade-offline event
            if event.get("evt") == "shade-offline":
                LOGGER.error(f"shade {self.sid} shade-offline event")
                self.updatePositions(self.posToPercent(event["currentPositions"]))
                self.controller.remove_gateway_event(event)

            # # battery-alert event
            if event.get("evt") == "battery-alert":
                LOGGER.error(f"shade {self.sid} battery-event")
                # the shade/event labels the battery different Status/level
                self.controller.shades_map[self.sid]["batteryStatus"] = event[
                    "batteryLevel"
                ]
                self.setDriver("GV6", event["batterylevel"], report=True, force=True)
                self.updatePositions(self.posToPercent(event["currentPositions"]))
                self.controller.remove_gateway_event(event)

    def updateData(self):
        """Updates the node's drivers and name from the controller's data map.

        This method retrieves the latest shade data from the controller, updates
        all relevant drivers on the ISY, and renames the node if the name has
        changed on the PowerView gateway.

        Returns:
            bool: True if the update was successful, False otherwise.
        """
        try:
            shade = self.controller.get_shade_data(self.sid)
            self.capabilities = shade.get("capabilities")
            LOGGER.debug(f"shade {self.sid} is {shade}")
            if self.name != shade["name"]:
                LOGGER.warning(f"Name error current:{self.name}  new:{shade['name']}")
                self.rename(shade["name"])
                LOGGER.warning(f"Renamed {self.name}")
            self.setDriver("ST", 0, report=True, force=True)
            self.reportCmd("DOF", 2)
            self.setDriver("GV1", shade["roomId"], report=True, force=True)
            self.setDriver("GV6", shade["batteryStatus"], report=True, force=True)
            self.setDriver("GV5", self.capabilities, report=True, force=True)
            self.updatePositions(shade["positions"])
            return True
        except Exception as ex:
            LOGGER.error(f"shade {self.sid} updateData error: {ex}", exc_info=True)
            return False

    # A dictionary mapping capabilities to the drivers that should be set.
    # This is a class-level variable for efficiency.
    _DRIVER_MAP = {
        7: [("GV2", "primary"), ("GV3", "secondary")],
        8: [("GV2", "primary"), ("GV3", "secondary")],
        0: [("GV2", "primary")],
        3: [("GV2", "primary")],
        6: [("GV3", "secondary")],
        1: [("GV2", "primary"), ("GV4", "tilt")],
        2: [("GV2", "primary"), ("GV4", "tilt")],
        4: [("GV2", "primary"), ("GV4", "tilt")],
        5: [("GV4", "tilt")],
        # The `else` case can be handled with a default lookup.
    }

    def updatePositions(self, positions):
        """Updates the shade's position drivers.

        This method updates the local shade data in the controller and sets the
        appropriate position drivers (primary, secondary, tilt) on the ISY
        based on the shade's capabilities.

        Args:
            positions (dict): A dictionary containing the shade's position data.

        Returns:
            bool: Always returns True.
        """
        LOGGER.info(f"shade:{self.sid}, positions:{positions}")

        self.controller.update_shade_data(self.sid, {"positions": positions})

        positions.setdefault("primary", None)
        positions.setdefault("secondary", None)
        positions.setdefault(
            "tilt", 0 if self.capabilities in self.tiltCapable else None
        )

        # Dispatch logic as above
        drivers_to_set = self._DRIVER_MAP.get(
            self.capabilities,
            [("GV2", "primary"), ("GV3", "secondary"), ("GV4", "tilt")],
        )

        for driver_key, position_key in drivers_to_set:
            pos_value = positions.get(position_key)
            self.setDriver(driver_key, pos_value)  # , report=True, force=True)

        return True

    def update_drivers_from_states(self, states):
        """Updates node drivers from TaHoma device states.

        Called when DeviceStateChangedEvent is received from TaHoma.
        Maps TaHoma state names to ISY drivers.

        Args:
            states (list): List of State objects from TaHoma device
        """
        LOGGER.debug(f"Updating drivers for {self.name} from TaHoma states")

        # Map TaHoma state names to driver keys
        state_driver_map = {
            "core:ClosureState": ("GV2", 100),  # Primary position (0-100)
            "core:DeploymentState": ("GV3", 100),  # Secondary position (0-100)
            "core:SlateOrientationState": ("GV4", 100),  # Tilt angle (0-100)
            "core:StatusState": ("ST", 2),  # Motion status (boolean)
            "core:DiscreteRSSILevelState": ("GV11", 25),  # Signal strength (index)
        }

        for state in states:
            state_name = state.name if hasattr(state, "name") else None
            if not state_name:
                continue

            if state_name in state_driver_map:
                driver_key, uom = state_driver_map[state_name]
                value = state.value if hasattr(state, "value") else None

                if value is not None:
                    # Convert value based on state type
                    if state_name == "core:StatusState":
                        # Status: "available" = 0 (not moving), other = 1 (moving)
                        driver_value = 0 if value == "available" else 1
                    elif state_name == "core:DiscreteRSSILevelState":
                        # RSSI: map string to index (0-5)
                        rssi_map = {
                            "verylow": 0,
                            "low": 1,
                            "normal": 2,
                            "good": 3,
                            "verygood": 4,
                            "excellent": 5,
                        }
                        driver_value = rssi_map.get(str(value).lower(), 2)
                    else:
                        # Position values: use as-is (already 0-100)
                        driver_value = int(value)

                    # Update driver
                    self.setDriver(
                        driver_key, driver_value, report=True, force=False, uom=uom
                    )
                    LOGGER.debug(
                        f"Updated {driver_key}={driver_value} from state {state_name}"
                    )

    def posToPercent(self, pos):
        """Converts a dictionary of raw position values to percentages.

        This is used to process position data from Gen 3 gateway events.

        Args:
            pos (dict): A dictionary of raw position values.

        Returns:
            dict: A new dictionary with the position values converted to percentages.
        """
        new_pos = {}
        for key, value in pos.items():
            try:
                if key == "etaInSeconds":
                    continue
                new_pos[key] = self.controller.toPercent(value)
            except (TypeError, ValueError) as ex:
                LOGGER.error(f"Failed to convert pos[{key}]='{value}' to percent: {ex}")
                new_pos[key] = 0

        return new_pos

    def cmdOpen(self, command):
        """Handles the 'Open' command from the ISY.

        Args:
            command (dict): The command payload from Polyglot.
        """
        LOGGER.info(f"cmd Shade Open {self.lpfx}, {command}")

        # TaHoma: use 'open' command
        self.execute_tahoma_command("open", [])

        self.reportCmd("OPEN", 2)
        LOGGER.debug(f"Exit {self.lpfx}")

    def cmdClose(self, command):
        """Handles the 'Close' command from the ISY.

        Args:
            command (dict): The command payload from Polyglot.
        """
        LOGGER.info(f"cmd Shade Close {self.lpfx}, {command}")

        # TaHoma: use 'close' command
        self.execute_tahoma_command("close", [])

        self.reportCmd("CLOSE", 2)
        LOGGER.debug(f"Exit {self.lpfx}")

    def cmdStop(self, command):
        """Handles the 'Stop' command from the ISY.

        Args:
            command (dict): The command payload from Polyglot.
        """
        LOGGER.info(f"cmd Shade Stop {self.lpfx}, {command}")

        if self.device_url:
            # TaHoma: use 'stop' command
            self.execute_tahoma_command("stop", [])
            self.reportCmd("STOP", 2)
        elif self.controller.generation == 3:
            # PowerView Gen 3
            shadeUrl = URL_SHADES_STOP.format(g=self.controller.gateway, id=self.sid)
            self.controller.put(shadeUrl)
            self.reportCmd("STOP", 2)
        elif self.controller.generation == 2:
            LOGGER.error(f"cmd Shade Stop error (none in gen2) {self.lpfx}, {command}")

    def cmdTiltOpen(self, command):
        """Handles the 'Tilt Open' command from the ISY.

        Args:
            command (dict): The command payload from Polyglot.
        """
        LOGGER.info(f"cmd Shade TiltOpen {self.lpfx}, {command}")

        # TaHoma: set orientation to 50 (mid-point, open slats)
        self.execute_tahoma_command("setOrientation", [50])

        self.reportCmd("TILTOPEN", 2)
        LOGGER.debug(f"Exit {self.lpfx}")

    def cmdTiltClose(self, command):
        """Handles the 'Tilt Close' command from the ISY.

        Args:
            command (dict): The command payload from Polyglot.
        """
        LOGGER.info(f"cmd Shade TiltClose {self.lpfx}, {command}")

        # TaHoma: set orientation to 0 (closed slats)
        self.execute_tahoma_command("setOrientation", [0])

        self.reportCmd("TILTCLOSE", 2)
        LOGGER.debug(f"Exit {self.lpfx}")

    def query(self, command=None):
        """Queries the node and reports all drivers to the ISY.

        Args:
            command (dict, optional): The command payload from Polyglot.
                                      Defaults to None.
        """
        LOGGER.info(f"cmd Query {self.lpfx}, {command}")
        self.updateData()
        self.reportDrivers()
        LOGGER.debug(f"Exit {self.lpfx}")

    def cmdSetpos(self, command=None):
        """Sets the position of the shade based on a command from the ISY.

        This method parses a command containing primary, secondary, or tilt
        positions and sends the corresponding request to the gateway.

        Args:
            command (dict, optional): The command payload from Polyglot,
                                      containing position query parameters.
                                      Defaults to None.
        """
        LOGGER.info(f"cmdSetpos {self.lpfx}, {command}")

        if not command:
            LOGGER.error("No positions given")
            return

        try:
            query = command.get("query", {})
            LOGGER.debug(f"Shade Setpos query {query}")

            key_map = {
                "SETPRIM.uom100": "primary",
                "SETSECO.uom100": "secondary",
                "SETTILT.uom100": "tilt",
            }

            pos = {
                name: int(query[key]) for key, name in key_map.items() if key in query
            }

            if pos:
                LOGGER.info(f"Shade Setpos {pos}")
                # TaHoma: convert to appropriate commands
                self.set_tahoma_positions(pos)
            else:
                LOGGER.error("Shade Setpos --nothing to set--")

        except (ValueError, TypeError, KeyError) as ex:
            LOGGER.error(f"Shade Setpos failed {self.lpfx}: {ex}", exc_info=True)

        LOGGER.debug(f"Exit {self.lpfx}")

    def set_tahoma_positions(self, pos):
        """Sets TaHoma device positions from position dictionary.

        Maps PowerView-style position dict to TaHoma commands.

        Args:
            pos (dict): Position dictionary with keys: primary, secondary, tilt
        """
        if "primary" in pos:
            # Primary position -> setClosure command (0=closed, 100=open)
            self.execute_tahoma_command("setClosure", [pos["primary"]])

        if "secondary" in pos:
            # Secondary position -> setDeployment command (for dual shades)
            self.execute_tahoma_command("setDeployment", [pos["secondary"]])

        if "tilt" in pos:
            # Tilt position -> setOrientation command (0=closed, 100=open)
            self.execute_tahoma_command("setOrientation", [pos["tilt"]])

    def execute_tahoma_command(self, command_name, parameters):
        """Executes a TaHoma command on this device.

        Args:
            command_name (str): TaHoma command name (e.g., 'setClosure', 'open', 'stop')
            parameters (list): Command parameters (e.g., [50] for 50% position)

        Returns:
            str: Execution ID or None on failure
        """
        import asyncio

        try:
            # Execute command via controller's TaHoma client
            exec_id = asyncio.run_coroutine_threadsafe(
                self.controller.tahoma_client.execute_command(
                    device_url=self.device_url,
                    command_name=command_name,
                    parameters=parameters,
                    label="ISY Control",
                ),
                self.controller.mainloop,
            ).result(timeout=10)

            if exec_id:
                LOGGER.info(
                    f"TaHoma command '{command_name}' executed on {self.name} "
                    f"(exec: {exec_id})"
                )
            else:
                LOGGER.warning(f"TaHoma command '{command_name}' failed on {self.name}")

            return exec_id

        except Exception as e:
            LOGGER.error(
                f"Error executing TaHoma command '{command_name}' on {self.name}: {e}",
                exc_info=True,
            )
            return None

    """
    UOMs:
    2: boolean
    25: index
    100: A Level from 0-255 e.g. brightness of a dimmable lamp
    107: Raw 1-byte unsigned value

    Driver controls:
    GV0: Custom Control 0 (Shade Id)
    ST: Status (In Motion)
    GV1: Custom Control 1 (Room Id)
    GV2: Custom Control 2 (Primary)
    GV3: Custom Control 3 (Secondary)
    GV4: Custom Control 4 (Tilt)
    GV5: Custom Control 5 (Capabilities)
    GV6: Custom Control 6 (Battery Status)
    """
    drivers = [
        {"driver": "GV0", "value": 0, "uom": 107, "name": "Shade Id"},
        {"driver": "ST", "value": 0, "uom": 2, "name": "In Motion"},
        {"driver": "GV1", "value": 0, "uom": 107, "name": "Room Id"},
        {"driver": "GV2", "value": None, "uom": 100, "name": "Primary"},
        {"driver": "GV3", "value": None, "uom": 100, "name": "Secondary"},
        {"driver": "GV4", "value": None, "uom": 100, "name": "Tilt"},
        {"driver": "GV5", "value": 0, "uom": 25, "name": "Capabilities"},
        {"driver": "GV6", "value": 0, "uom": 25, "name": "Battery Status"},
    ]

    """
    Commands that this node can handle.
    Should match the 'accepts' section of the nodedef file.
    """
    commands = {
        "OPEN": cmdOpen,
        "CLOSE": cmdClose,
        "STOP": cmdStop,
        "TILTOPEN": cmdTiltOpen,
        "TILTCLOSE": cmdTiltClose,
        "QUERY": query,
        "SETPOS": cmdSetpos,
    }


###################
# Shade sub-classes
###################


class ShadeNoTilt(Shade):
    """Shade node for shades with primary and secondary controls, but no tilt."""

    id = "shadenotiltid"

    drivers = [
        {"driver": "GV0", "value": 0, "uom": 107, "name": "Shade Id"},
        {"driver": "ST", "value": 0, "uom": 2, "name": "In Motion"},
        {"driver": "GV1", "value": 0, "uom": 107, "name": "Room Id"},
        {"driver": "GV2", "value": None, "uom": 100, "name": "Primary"},
        {"driver": "GV3", "value": None, "uom": 100, "name": "Secondary"},
        {"driver": "GV5", "value": 0, "uom": 25, "name": "Capabilities"},
        {"driver": "GV6", "value": 0, "uom": 25, "name": "Battery Status"},
    ]


class ShadeOnlyPrimary(Shade):
    """Shade node for shades with only a primary position control."""

    id = "shadeonlyprimid"

    drivers = [
        {"driver": "GV0", "value": 0, "uom": 107, "name": "Shade Id"},
        {"driver": "ST", "value": 0, "uom": 2, "name": "In Motion"},
        {"driver": "GV1", "value": 0, "uom": 107, "name": "Room Id"},
        {"driver": "GV2", "value": None, "uom": 100, "name": "Primary"},
        {"driver": "GV5", "value": 0, "uom": 25, "name": "Capabilities"},
        {"driver": "GV6", "value": 0, "uom": 25, "name": "Battery Status"},
    ]
