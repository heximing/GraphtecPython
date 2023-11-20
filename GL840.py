from bs4 import BeautifulSoup
from requests import get
import pandas as pd
import pyvisa
import time


class Graphtec:

    def __init__(self, address, name_string: str = "GRAPHTEC"):
        self._my_instrument = None  # PyVISA instance
        self._ident = None
        self._address = address  # string representation of the USB/TCP/IP device to connect to
        self._name_string = name_string
        # self.data = []  # Holds measurement data
        self.connected = self.connect()
        """
        Can be setup on Graphtec with "Menu > I/F > IP ADDRESS" (change with buttons)
        Sometimes errors arise here if you can not connect,
        restarting the Graphtec or doing "Menu > I/F > Apply Setting" sometimes helps.
        Also, try if you can visit the ip address in browser directly.
        """
        # print(datetime.datetime.now(), "; debug msg: self.connected =", type(self.connected), str(self.connected))

    def connect(self) -> bool:
        """
        Returns:
            boolean: True if a connection is opened properly
        """
        connected = False
        _tcpip_gl = None
        try:
            rm = pyvisa.ResourceManager()  # Need a resourcemanager to communicate with Graphtec via PyVisa
            # print("Listing rm.list_resources()...", rm.list_resources())
            _tcpip_gl = f"TCPIP::{self._address}::8023::SOCKET"  # TCPIP address to contact
            self._my_instrument = rm.open_resource(_tcpip_gl, write_termination='\n', read_termination='\r\n')
            """
            !!! Attention !!!
            Creating a <class 'pyvisa.resources.usb.USBInstrument'> not necessarily guarantee the equipment is present.
            Only at 1st time call pyvisa.ResourceManager(), open_resource() will generate pyvisa.errors.VisaIOError;
            if equipment is disconnected/re-connected during testing, open_resource() will succeed!!
            Therefore, connected = True here does not guarantee the equipment is present.
            Need to rely on identify_device(), i.e. query("*IDN?")
            """
            connected = bool(self.identify_device(tcpip=_tcpip_gl))
        except OSError as msg:
            print(self._name_string + ' not found [{}]'.format(msg))
            raise
        except AttributeError as msg:
            print(msg, "; in connect() in GL840.py")
            raise
        except pyvisa.errors.VisaIOError as msg:
            print(msg, "; in connect() in GL840.py; cannot connect to:", _tcpip_gl, "; but keep going...")
        return connected

    def identify_device(self, tcpip) -> bool:
        """
        Using connection to device, ask the ID and make sure it matches the expected value.
        Returns:
            boolean: True if a connection is opened properly
        """
        try:
            self._ident = self._my_instrument.query("*IDN?")
            print(time.ctime(), "; identify_device(): self._ident =", self._ident)
            assert self._name_string in self._ident
            return True
        except (AssertionError, TypeError, pyvisa.errors.VisaIOError) as msg:
            self.close()
            self.connected = False
            print('Expected "' + self._name_string + '" but seeing "' + str(self._ident) + '" @ ' + tcpip)
            print(time.ctime(), msg, "; identify_device() @ GL840.py; set self.connected = False; keep going...")
            return False

    def append_graphtec_readings(self, num: int = 2) -> list[list[list[str]]] | list[None]:
        """
        Find all the measurements of the channels and append to and return data_list
        Args:
            num: number of readings in total
        """
        # Format URL
        address_channel_data = f"http://{self._address}/digital.cgi?chgrp=13"

        # Get http response
        response = get(address_channel_data)                        # Get response from the channel data page

        data_list = []
        data_dict = {}
        for i in range(num):
            # Create response table
            soup_object = BeautifulSoup(response.text, 'html.parser')   # Create a soup object from this, which is used to create a table
            table = soup_object.find(lambda tag: tag.name == 'table')   # Table with all the channels as subtables > based on the HTML table class > example: [table: [table, table, table]]
            channel_readings_html = table.findAll('table')              # Tables of all the individual channels > Search for table again to get: [table, table, table], each one corresponds to one channel

            # Loop over table to yield formatted data
            channels_data = []                                          # Holds all the found data > in format: [('CH 1', '+  10', 'degC'), (CH2 ....]

            for channel_read_html in channel_readings_html:
                reading_html = channel_read_html.find_all('b')          # Returns a row for each measurement channel with relevant data > [<b> CH 1</b>, <b> -------</b>, <b> degC</b>]

                reading_list = [read_tag.get_text(strip=True) for read_tag in reading_html]  # Strips the string of its unicode characters and puts it into a list > ['CH 1', '-------', 'degC']
                channels_data.append(reading_list)

            # Append the data to the list
            data_list.append(channels_data)
            time.sleep(0.1)
        """
        [
        [['CH 1', '+ 21.48', 'degC'], ['CH 2', '+ 21.76', 'degC']], ...  # depending on how many CH the device has
        [['CH 1', '+ 21.47', 'degC'], ['CH 2', '+ 21.75', 'degC']], ...  # depending on how many CH the device has
        ...
        ...  # depending on the "num" input parameter
        ]
        """
        return data_list

    def add_channel_data_to_df(self, data_list: list | None = None) -> pd.DataFrame | None:
        """Post processing method to format data_list into a Pandas DataFrame"""

        if data_list is None or data_list == [] or len(data_list) == 0:
            print(time.ctime(), "; no data input; skipped...")
        else:
            name_index = 0      # Format is ['CH 1', '23.56', 'degC']
            reading_index = 1   # so index 0, 1 and 2 are, respectively channel name, value reading and unit.
            unit_index = 2

            channel_count = len(data_list[0])  # Amount of channels; might depend on Graphtec device (I have 20)
            df = pd.DataFrame()

            # Loop over each channel
            for channel_ind in range(channel_count):

                channel_name = data_list[0][channel_ind][name_index]    # get the channel name
                channel_unit = data_list[0][channel_ind][unit_index]    # and unit
                column_name = f"GRPH {channel_name} [{channel_unit}]"   # Format column name "GRPH CH1 [degC]"

                channel_readings = []                                   # Stores the channel data > [0.0, 0.1, 0.0 ....]

                # Loop over each row and retrieve channel data
                for row in data_list:
                    channel_reading = row[channel_ind][reading_index]   # Read the data of channel for this row

                    # Value formatting
                    try:
                        # Float for other values, remove spaces in order to have +/-
                        channel_reading = float(channel_reading.replace(' ', ''))
                    except ValueError:  # ValueError: could not convert string to float: 'BURNOUT'
                        channel_reading = None

                    channel_readings.append(channel_reading)

                df[column_name] = channel_readings          # Add a new column with data

            return df

    def add_channel_data_to_dict(self, data_list: list | None = None) -> dict | None:
        """
        Post processing method to format data_list into a Dictionary
        !!! Attention !!!
            1. Only get the last reading even if data_list include multiple readings (num > 2)
            2. Assume the unit is always 'degC'
        """

        if data_list is None or data_list == [] or len(data_list) <= 0:
            print(time.ctime(), "; no data input; skipped...")
        else:
            data_dict = {}
            for a_ch in data_list[-1]:
                try:
                    _data = float(a_ch[1].replace(" ", ""))
                except ValueError:  # ValueError: could not convert string to float: 'BURNOUT'
                    _data = None
                data_dict[str(a_ch[0])] = _data
            return data_dict

    def close(self):
        self._my_instrument.close()
        self._my_instrument = None  # PyVISA instance
        print("self._my_instrument.close() in GL840.py")


if __name__ == "__main__":

    graphtec = Graphtec("192.168.0.1")
    get_list = graphtec.append_graphtec_readings(num=1)
    print(time.ctime(), type(get_list), get_list)
    # get_dict = graphtec.add_channel_data_to_dict(graphtec.append_graphtec_readings(num=1))
    get_dict = graphtec.add_channel_data_to_dict(get_list)
    print(time.ctime(), type(get_dict), get_dict)
    graphtec.close()
