import os
import logging
import logging.config
import re
import random, string
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
import urllib
import json


import requests
from requests.exceptions import ConnectionError, HTTPError, Timeout
import pytz


from consts import LookupConventions as const
from exceptions import LookupError, APIKeyMissingError, NoResult

UTC = pytz.UTC
timestamp_now = datetime.utcnow().replace(tzinfo=UTC)


class LookupLib(object):
    """

    This class provides a homogeneous interface to three different Amateur Radio Callsign lookup sources:

    1. Clublog.org (daily updated XML File)
    2. Clublog.org (HTTPS lookup)
    3. Country-files.com (infrequently updated PLIST File)

    The class provides getters to access the data in a structured way. Even the interface is the same
    for all lookup sources, the returning data can be different. The documentation of the various
    methods provide more detail.

    By default, LookupLib requires an Internet connection to download the libraries or perform the
    lookup against the Clublog API.

    Args:
        lookuptype (str) : "clublogxml" or "clublogapi" or "countryfile"
        apikey (str): Clublog API Key
        filename (str, optional): Filename for Clublog XML or Country-files.com cty.plist file
        logger (logging.getLogger(__name__), optional): Python logger

    """
    def __init__(self, lookuptype = "clublogxml", apikey=None, filename=None, logger=None):

        self._logger = None
        if logger:
            self._logger = logger
        else:
            self._logger = logging.getLogger(__name__)
            self._logger.addHandler(logging.NullHandler())

        self._apikey = apikey
        self._download = True
        self._lib_filename = filename

        if self._lib_filename:
            self._download = False

        self._callsign_exceptions_index = {}
        self._invalid_operations_index = {}
        self._zone_exceptions_index = {}

        self._entities = {}
        self._callsign_exceptions = {}
        self._invalid_operations = {}
        self._zone_exceptions = {}
        self._lookuptype = lookuptype



        if self._lookuptype == "clublogxml":
            self._load_clublogXML(apikey=self._apikey, cty_file=self._lib_filename)
        elif self._lookuptype == "countryfile":
            self._load_countryfile()
        elif self._lookuptype == "clublogapi":
            pass
        else:
            raise AttributeError("Lookup type missing")

    def lookup_entity(self, entity=None):
        """Returns lookup data of a ADIF Entity

        Args:
            entity (int): ADIF identifier of country

        Returns:
            dict: Dictionary containing the country specific data

        Raises:
            NoResult: No matching entity found

        Note:
            This method is available for the following lookup type

            - clublogxml

        """


        if entity is None:
            raise LookupError

        try:
            entity = int(entity)
            if entity in self._entities:
                return self._entities[entity]
            else:
                raise NoResult
        except:
            raise NoResult

    def lookup_callsign(self, callsign=None, timestamp=timestamp_now):
        """
        Returns lookup data if an exception exists for a callsign

        Args:
            callsign (string): Amateur radio callsign
            timestamp (datetime, optional): datetime in UTC (tzinfo=pytz.UTC)

        Returns:
            dict: Dictionary containing the country specific data of the callsign

        Raises:
            NoResult: No matching callsign found
            APIKeyMissingError: API Key for Clublog missing or incorrect

        Note:
            This method is available for

            - clublogxml
            - clublogapi
            - countryfile

        """
        callsign = callsign.strip().upper()

        if self._lookuptype == "clublogapi":
            return self._lookup_clublogAPI(
                       callsign=callsign,
                       timestamp=timestamp,
                       apikey=self._apikey)

        if self._lookuptype == "clublogxml" or self._lookuptype == "countryfile":

            if callsign in self._callsign_exceptions_index:
                for item in self._callsign_exceptions_index[callsign]:

                    # startdate < timestamp
                    if const.START in self._callsign_exceptions[item] and not const.END in self._callsign_exceptions[item]:
                        if self._callsign_exceptions[item][const.START] < timestamp:
                            return self._callsign_exceptions[item]

                    # enddate > timestamp
                    elif not const.START in self._callsign_exceptions[item] and const.END in self._callsign_exceptions[item]:
                        if self._callsign_exceptions[item][const.END] > timestamp:
                            return self._callsign_exceptions[item]

                    # startdate > timestamp > enddate
                    elif const.START in self._callsign_exceptions[item].keys() and const.END in self._callsign_exceptions[item]:
                        if self._callsign_exceptions[item][const.START] < timestamp \
                                and self._callsign_exceptions[item][const.END] > timestamp:
                            return self._callsign_exceptions[item]

                    # no startdate or enddate available
                    else:
                        return self._callsign_exceptions[item]

        # no matching case
        raise NoResult

    def lookup_prefix(self, prefix, timestamp=timestamp_now):
        """
        Returns lookup data of a Prefix

        Args:
            prefix (string): Prefix of a Amateur Radio callsign
            timestamp (datetime, optional): datetime in UTC (tzinfo=pytz.UTC)

        Returns:
            dict: Dictionary containing the country specific data of the Prefix

        Raises:
            NoResult: No matching Prefix found
            APIKeyMissingError: API Key for Clublog missing or incorrect

        Note:
            This method is available for

            - clublogxml
            - countryfile

        """

        prefix = prefix.strip().upper()

        if self._lookuptype == "clublogxml" or self._lookuptype == "countryfile":

            if prefix in self._prefixes_index:
                for item in self._prefixes_index[prefix]:

                    # startdate < timestamp
                    if const.START in self._prefixes[item] and not const.END in self._prefixes[item]:
                        if self._prefixes[item][const.START] < timestamp:
                            return self._prefixes[item]

                    # enddate > timestamp
                    elif not const.START in self._prefixes[item] and const.END in self._prefixes[item]:
                        if self._prefixes[item][const.END] > timestamp:
                            return self._prefixes[item]

                    # startdate > timestamp > enddate
                    elif const.START in self._prefixes[item] and const.END in self._prefixes[item]:
                        if self._prefixes[item][const.START] < timestamp and self._prefixes[item][const.END] > timestamp:
                            return self._prefixes[item]

                    # no startdate or enddate available
                    else:
                        return self._prefixes[item]

        raise NoResult

    def is_invalid_operation(self, callsign, timestamp=datetime.utcnow().replace(tzinfo=UTC)):
        """
        Returns True if an operations is known as invalid

        Args:
            callsign (string): Amateur Radio callsign
            timestamp (datetime, optional): datetime in UTC (tzinfo=pytz.UTC)

        Returns:
            bool: True if a record exists for this callsign (at the given time)

        Raises:
            NoResult: No matching callsign found
            APIKeyMissingError: API Key for Clublog missing or incorrect

        Note:
            This method is available for

            - clublogxml

        """

        callsign = callsign.strip().upper()

        if self._lookuptype == "clublogxml":

            if callsign in self._invalid_operations_index:
                for item in self._invalid_operations_index[callsign]:

                    # startdate < timestamp
                    if const.START in self._invalid_operations[item] \
                            and not const.END in self._invalid_operations[item]:
                        if self._invalid_operations[item][const.START] < timestamp:
                           return True

                    # enddate > timestamp
                    elif not const.START in self._invalid_operations[item] \
                            and const.END in self._invalid_operations[item]:
                        if self._invalid_operations[item][const.END] > timestamp:
                           return True

                    # startdate > timestamp > enddate
                    elif const.START in self._invalid_operations[item] and const.END in self._invalid_operations[item]:
                        if self._invalid_operations[item][const.START] < timestamp \
                                and self._invalid_operations[item][const.END] > timestamp:
                           return True

                    # no startdate or enddate available
                    else:
                        return True

        #no matching case
        raise NoResult


    def lookup_zone_exception(self, callsign, timestamp=datetime.utcnow().replace(tzinfo=UTC)):
        """
        Returns a CQ Zone if an exception exists for the given callsign

        Args:
        callsign (string): Amateur radio callsign
        timestamp (datetime, optional): datetime in UTC (tzinfo=pytz.UTC)

        Returns:
            int: Value of the the CQ Zone exception which exists for this callsign (at the given time)

        Raises:
            NoResult: No matching callsign found
            APIKeyMissingError: API Key for Clublog missing or incorrect

        Note:
            This method is available for

            - clublogxml

        """

        callsign = callsign.strip().upper()

        if self._lookuptype == "clublogxml":

            if callsign in self._zone_exceptions_index:
                for item in self._zone_exceptions_index[callsign]:

                    # startdate < timestamp
                    if const.START in self._zone_exceptions[item] and not const.END in self._zone_exceptions[item]:
                        if self._zone_exceptions[item][const.START] < timestamp:
                            return self._zone_exceptions[item][const.CQZ]

                    # enddate > timestamp
                    elif not const.START in self._zone_exceptions[item] and const.END in self._zone_exceptions[item]:
                        if self._zone_exceptions[item][const.END] > timestamp:
                            return self._zone_exceptions[item][const.CQZ]

                    # startdate > timestamp > enddate
                    elif const.START in self._zone_exceptions[item] and const.END in self._zone_exceptions[item]:
                        if self._zone_exceptions[item][const.START] < timestamp \
                                and self._zone_exceptions[item][const.END] > timestamp:
                            return self._zone_exceptions[item][const.CQZ]

                    # no startdate or enddate available
                    else:
                        return self._zone_exceptions[item][const.CQZ]

        #no matching case
        raise NoResult

    def _lookup_clublogAPI(self, callsign=None, timestamp=timestamp_now, url="https://secure.clublog.org/dxcc", apikey=None):
        """ Set up the Lookup object for Clublog Online API
        """

        params = {"year" : timestamp.strftime("%Y"),
            "month" : timestamp.strftime("%m"),
            "day" : timestamp.strftime("%d"),
            "hour" : timestamp.strftime("%H"),
            "minute" : timestamp.strftime("%M"),
            "api" : apikey,
            "full" : "1",
            "call" : callsign
        }

        encodeurl = url + "?" + urllib.urlencode(params)
        response = requests.get(encodeurl, timeout=5)

        if not self._check_html_response(response):
            raise LookupError

        jsonLookup = json.loads(response.text)
        lookup = {}

        for item in jsonLookup:
            if item == "Name": lookup[const.COUNTRY] = str(jsonLookup["Name"])
            elif item == "DXCC": lookup[const.ADIF] = int(jsonLookup["DXCC"])
            elif item == "Lon": lookup[const.LONGITUDE] = float(jsonLookup["Lon"])
            elif item == "Lat": lookup[const.LATITUDE] = float(jsonLookup["Lat"])
            elif item == "CQZ": lookup[const.CQZ] = int(jsonLookup["CQZ"])
            elif item == "Continent": lookup[const.CONTINENT] = str(jsonLookup["Continent"])

        if lookup[const.ADIF] == 0:
            raise NoResult
        else:
            return lookup

    def _load_clublogXML(self,
                        url="https://secure.clublog.org/cty.php",
                        apikey=None,
                        cty_file=None):
        """ Load and process the ClublogXML file either as a download or from file
        """

        if self._download:
            cty_file = self._download_file(
                    url = url,
                    apikey = apikey)
        else:
            cty_file = self._lib_filename

        header = self._extract_clublog_header(cty_file)
        cty_file = self._remove_clublog_xml_header(cty_file)
        cty_dict = self._parse_clublog_xml(cty_file)

        self._entities = cty_dict["entities"]
        self._callsign_exceptions = cty_dict["call_exceptions"]
        self._prefixes = cty_dict["prefixes"]
        self._invalid_operations = cty_dict["invalid_operations"]
        self._zone_exceptions = cty_dict["zone_exceptions"]

        self._callsign_exceptions_index = cty_dict["call_exceptions_index"]
        self._prefixes_index = cty_dict["prefixes_index"]
        self._invalid_operations_index = cty_dict["invalid_operations_index"]
        self._zone_exceptions_index = cty_dict["zone_exceptions_index"]

        return True

    def _load_countryfile(self,
                         url="http://www.country-files.com/cty/cty.plist", 
                         country_mapping_filename="countryfilemapping.json", 
                         cty_file=None):
        """ Load and process the ClublogXML file either as a download or from file
        """

        cwdFile = os.path.abspath(os.path.join(os.getcwd(), country_mapping_filename))
        pkgFile = os.path.abspath(os.path.join(os.path.dirname(__file__), country_mapping_filename))

        print cwdFile
        print pkgFile


        # from cwd
        if os.path.exists(cwdFile):
            country_mapping_filename = cwdFile
        # from package
        elif os.path.exists(pkgFile):
            country_mapping_filename = pkgFile
        else:
            country_mapping_filename = None

        if self._download:
            cty_file = self._download_file(url=url)
        else:
            cty_file = os.path.abspath(cty_file)

        cty_dict = self._parse_country_file(cty_file, country_mapping_filename)
        self._callsign_exceptions = cty_dict["exceptions"]
        self._prefixes = cty_dict["prefixes"]
        self._callsign_exceptions_index = cty_dict["exceptions_index"]
        self._prefixes_index = cty_dict["prefixes_index"]

        return True

    def _download_file(self, url, apikey=None):
        """ Download lookup files either from Clublog or Country-files.com
        """
        import gzip
        import tempfile

        cty = {}
        cty_date = ""
        cty_file_path = None

        filename = None

        # download file
        if apikey: # clublog
            response = requests.get(url+"?api="+apikey, timeout=10)
        else: # country-files.com
            response = requests.get(url, timeout=10)

        if not self._check_html_response(response):
            raise LookupError

        #Clublog Webserver Header
        if "Content-Disposition" in response.headers:
            f = re.search('filename=".+"', response.headers["Content-Disposition"])
            if f:
                f = f.group(0)
                filename = re.search('".+"', f).group(0).replace('"', '')

        #Country-files.org webserver header
        else:
            f = re.search('/.{4}plist$', url)
            if f:
                f = f.group(0)
                filename = f[1:]

        if not filename:
            filename = "cty_" + self._generate_random_word(5)

        download_file_path = os.path.join(tempfile.gettempdir(), filename)
        with open(download_file_path, "w") as download_file:
            download_file.write(response.content)
        self._logger.debug(str(download_file_path) + " successfully downloaded")

        # unzip file, if gz
        if os.path.splitext(download_file_path)[1][1:] == "gz":
            with gzip.open(download_file_path, "r") as download_file:
                cty_file_path = os.path.join(os.path.splitext(download_file_path)[0])
                with open(cty_file_path, "w") as cty_file:
                    cty_file.write(download_file.read())
            self._logger.debug(str(cty_file_path) + " successfully extracted")
        else:
            cty_file_path = download_file_path

        return cty_file_path
    
    def _extract_clublog_header(self, cty_xml_filename):
        """
        Extract the header of the Clublog XML File
        """

        cty_header = {}

        try: 
            with open(cty_xml_filename, "r") as cty:
                raw_header = cty.readline()

            cty_date = re.search("date='.+'", raw_header)
            if cty_date: 
                cty_date = cty_date.group(0).replace("date=", "").replace("'", "")
                cty_date = datetime.strptime(cty_date[:19], '%Y-%m-%dT%H:%M:%S')
                cty_date.replace(tzinfo=UTC)
                cty_header["Date"] = cty_date
            
            cty_ns = re.search("xmlns='.+[']", raw_header)
            if cty_ns: 
                cty_ns = cty_ns.group(0).replace("xmlns=", "").replace("'", "")
                cty_header['NameSpace'] = cty_ns
        
            if len(cty_header) == 2:
                self._logger.debug("Header successfully retrieved from CTY File")
            elif len(cty_header) < 2:
                self._logger.warning("Header could only be partically retrieved from CTY File")
                self._logger.warning("Content of Header: ")
                for key in cty_header:
                    self._logger.warning(str(key)+": "+str(cty_header[key]))
            return cty_header
        
        except Exception as e: 
            self._logger.error("Clublog CTY File could not be opened / modified")
            self._logger.error("Error Message: " + str(e))
            return


    def _remove_clublog_xml_header(self, cty_xml_filename):
        """ 
            remove the header of the Clublog XML File to make it
            properly parseable for the python ElementTree XML parser
        """        
        import tempfile

        try:
            with open(cty_xml_filename, "r") as f:
                content = f.readlines()
            
            cty_dir = tempfile.gettempdir()
            cty_name = os.path.split(cty_xml_filename)[1]
            cty_xml_filename_no_header = os.path.join(cty_dir, "NoHeader_"+cty_name)

            with open(cty_xml_filename_no_header, "w") as f:
                f.writelines("<clublog>\n\r")
                f.writelines(content[1:])

            self._logger.debug("Header successfully modified for XML Parsing")
            return cty_xml_filename_no_header

        except Exception as e:
            self._logger.error("Clublog CTY could not be opened / modified")
            self._logger.error("Error Message: " + str(e))
            return

    def _parse_clublog_xml(self, cty_xml_filename):
        """
        parse the content of a clublog XML file and return the
        parsed values in dictionaries

        """

        entities = {}
        call_exceptions = {}
        prefixes = {}
        invalid_operations = {}
        zone_exceptions = {}

        call_exceptions_index = {}
        prefixes_index = {}
        invalid_operations_index = {}
        zone_exceptions_index = {}

        cty_tree = ET.parse(cty_xml_filename)
        root = cty_tree.getroot()

        #retrieve ADIF Country Entities
        cty_entities = cty_tree.find("entities")
        if len(cty_entities) > 1:
            for cty_entity in cty_entities:
                entity = {}
                for item in cty_entity:
                    if item.tag == "name":
                        entity[const.COUNTRY] = str(item.text)
                    elif item.tag == "prefix":
                        entity[const.PREFIX] = str(item.text)
                    elif item.tag == "deleted":
                        if item.text == "TRUE":
                            entity[const.DELETED] = True
                        else:
                            entity[const.DELETED] = False
                    elif item.tag == "cqz":
                        entity[const.CQZ] = int(item.text)
                    elif item.tag == "cont":
                        entity[const.CONTINENT] = str(item.text)
                    elif item.tag == "long":
                        entity[const.LONGITUDE] = float(item.text)*(-1)
                    elif item.tag == "lat":
                        entity[const.LATITUDE] = float(item.text)
                    elif item.tag == "start":
                        dt = datetime.strptime(item.text[:19], '%Y-%m-%dT%H:%M:%S')
                        entity[const.START] = dt.replace(tzinfo=UTC)
                    elif item.tag == "end":
                        dt = datetime.strptime(item.text[:19], '%Y-%m-%dT%H:%M:%S')
                        entity[const.END] = dt.replace(tzinfo=UTC)
                    elif item.tag == "whitelist":
                        if item.text == "TRUE":
                            entity[const.WHITELIST] = True
                        else:
                            entity[const.WHITELIST] = False
                    elif item.tag == "whitelist_start":
                        dt = datetime.strptime(item.text[:19], '%Y-%m-%dT%H:%M:%S')
                        entity[const.WHITELIST_START] = dt.replace(tzinfo=UTC)
                    elif item.tag == "whitelist_end":
                        dt = datetime.strptime(item.text[:19], '%Y-%m-%dT%H:%M:%S')
                        entity[const.WHITELIST_END] = dt.replace(tzinfo=UTC)
                entities[int(cty_entity[0].text)] = entity
            self._logger.debug(str(len(entities))+" Entities added")
        else:
            raise Exception("No Country Entities detected in XML File")


        cty_exceptions = cty_tree.find("exceptions")
        if len(cty_exceptions) > 1:
            for cty_exception in cty_exceptions:
                call_exception = {}
                for item in cty_exception:
                    if item.tag == "call":
                        call = str(item.text)
                        if call in call_exceptions_index.keys():
                            call_exceptions_index[call].append(int(cty_exception.attrib["record"]))
                        else:
                            call_exceptions_index[call] = [int(cty_exception.attrib["record"])]
                    elif item.tag == "entity":
                        call_exception[const.COUNTRY] = str(item.text)
                    elif item.tag == "adif":
                        call_exception[const.ADIF] = int(item.text)
                    elif item.tag == "cqz":
                        call_exception[const.CQZ] = int(item.text)
                    elif item.tag == "cont":
                        call_exception[const.CONTINENT] = str(item.text)
                    elif item.tag == "long":
                        call_exception[const.LONGITUDE] = float(item.text)*(-1)
                    elif item.tag == "lat":
                        call_exception[const.LATITUDE] = float(item.text)
                    elif item.tag == "start":
                        dt = datetime.strptime(item.text[:19], '%Y-%m-%dT%H:%M:%S')
                        call_exception[const.START] = dt.replace(tzinfo=UTC)
                    elif item.tag == "end":
                        dt = datetime.strptime(item.text[:19], '%Y-%m-%dT%H:%M:%S')
                        call_exception[const.END] = dt.replace(tzinfo=UTC)
                    call_exceptions[int(cty_exception.attrib["record"])] = call_exception

            self._logger.debug(str(len(call_exceptions))+" Exceptions added")
            self._logger.debug(str(len(call_exceptions_index))+" unique Calls in Index ")

        else:
            raise Exception("No Exceptions detected in XML File")


        cty_prefixes = cty_tree.find("prefixes")
        if len(cty_prefixes) > 1:
            for cty_prefix in cty_prefixes:
                prefix = {}
                for item in cty_prefix:
                    pref = None
                    if item.tag == "call":

                        #create index for this prefix
                        call = str(item.text)
                        if call in prefixes_index.keys():
                            prefixes_index[call].append(int(cty_prefix.attrib["record"]))
                        else:
                            prefixes_index[call] = [int(cty_prefix.attrib["record"])]
                    if item.tag == "entity":
                        prefix[const.COUNTRY] = str(item.text)
                    elif item.tag == "adif":
                        prefix[const.ADIF] = int(item.text)
                    elif item.tag == "cqz":
                        prefix[const.CQZ] = int(item.text)
                    elif item.tag == "cont":
                        prefix[const.CONTINENT] = str(item.text)
                    elif item.tag == "long":
                        prefix[const.LONGITUDE] = float(item.text)*(-1)
                    elif item.tag == "lat":
                        prefix[const.LATITUDE] = float(item.text)
                    elif item.tag == "start":
                        dt = datetime.strptime(item.text[:19], '%Y-%m-%dT%H:%M:%S')
                        prefix[const.START] = dt.replace(tzinfo=UTC)
                    elif item.tag == "end":
                        dt = datetime.strptime(item.text[:19], '%Y-%m-%dT%H:%M:%S')
                        prefix[const.END] = dt.replace(tzinfo=UTC)
                    prefixes[int(cty_prefix.attrib["record"])] = prefix

            self._logger.debug(str(len(prefixes))+" Prefixes added")
            self._logger.debug(str(len(prefixes_index))+" unique Prefixes in Index")
        else:
            raise Exception("No Prefixes detected in XML File")

        cty_inv_operations = cty_tree.find("invalid_operations")
        if len(cty_inv_operations) > 1:
            for cty_inv_operation in cty_inv_operations:
                invalid_operation = {}
                for item in cty_inv_operation:
                    call = None
                    if item.tag == "call":
                        call = str(item.text)
                        if call in invalid_operations_index.keys():
                            invalid_operations_index[call].append(int(cty_inv_operation.attrib["record"]))
                        else:
                            invalid_operations_index[call] = [int(cty_inv_operation.attrib["record"])]

                    elif item.tag == "start":
                        dt = datetime.strptime(item.text[:19], '%Y-%m-%dT%H:%M:%S')
                        invalid_operation[const.START] = dt.replace(tzinfo=UTC)
                    elif item.tag == "end":
                        dt = datetime.strptime(item.text[:19], '%Y-%m-%dT%H:%M:%S')
                        invalid_operation[const.END] = dt.replace(tzinfo=UTC)
                    invalid_operations[int(cty_inv_operation.attrib["record"])] = invalid_operation

            self._logger.debug(str(len(invalid_operations))+" Invalid Operations added")
            self._logger.debug(str(len(invalid_operations_index))+" unique Calls in Index")
        else:
            raise Exception("No records for invalid operations detected in XML File")


        cty_zone_exceptions = cty_tree.find("zone_exceptions")
        if len(cty_zone_exceptions) > 1:
            for cty_zone_exception in cty_zone_exceptions:
                zoneException = {}
                for item in cty_zone_exception:
                    call = None
                    if item.tag == "call":
                        call = str(item.text)
                        if call in zone_exceptions_index.keys():
                            zone_exceptions_index[call].append(int(cty_zone_exception.attrib["record"]))
                        else:
                            zone_exceptions_index[call] = [int(cty_zone_exception.attrib["record"])]

                    elif item.tag == "zone":
                        zoneException[const.CQZ] = int(item.text)
                    elif item.tag == "start":
                        dt = datetime.strptime(item.text[:19], '%Y-%m-%dT%H:%M:%S')
                        zoneException[const.START] = dt.replace(tzinfo=UTC)
                    elif item.tag == "end":
                        dt = datetime.strptime(item.text[:19], '%Y-%m-%dT%H:%M:%S')
                        zoneException[const.END] = dt.replace(tzinfo=UTC)
                    zone_exceptions[int(cty_zone_exception.attrib["record"])] = zoneException

            self._logger.debug(str(len(zone_exceptions))+" Zone Exceptions added")
            self._logger.debug(str(len(zone_exceptions_index))+" unique Calls in Index")
        else:
            raise Exception("No records for zone exceptions detected in XML File")

        result = {
            "entities" : entities,
            "call_exceptions" : call_exceptions,
            "prefixes" : prefixes,
            "invalid_operations" : invalid_operations,
            "zone_exceptions" : zone_exceptions,
            "prefixes_index" : prefixes_index,
            "call_exceptions_index" : call_exceptions_index,
            "invalid_operations_index" : invalid_operations_index,
            "zone_exceptions_index" : zone_exceptions_index,
        }
        return result

    def _parse_country_file(self, cty_file, country_mapping_filename=None):
        """
        Parse the content of a PLIST file from country-files.com return the
        parsed values in dictionaries.
        Country-files.com provides Prefixes and Exceptions

        """

        import plistlib
        
        cty_list = None
        entities = {}
        exceptions = {}
        prefixes = {}

        exceptions_index = {}
        prefixes_index = {}

        exceptions_counter = 0
        prefixes_counter = 0

        mapping = None

        with open(country_mapping_filename, "r") as f:
            mapping = json.loads(f.read())

        cty_list = plistlib.readPlist(cty_file)

        for item in cty_list:
            entry = {}
            call = str(item)
            entry[const.COUNTRY] = str(cty_list[item]["Country"])
            if mapping:
                 entry[const.ADIF] = int(mapping[cty_list[item]["Country"]])
            entry[const.CQZ] = int(cty_list[item]["CQZone"])
            entry[const.ITUZ] = int(cty_list[item]["ITUZone"])
            entry[const.CONTINENT] = str(cty_list[item]["Continent"])
            entry[const.LATITUDE] = float(cty_list[item]["Latitude"])
            entry[const.LONGITUDE] = float(cty_list[item]["Longitude"])

            if cty_list[item]["ExactCallsign"]:
                if call in exceptions_index.keys():
                    exceptions_index[call].append(exceptions_counter)
                else:
                    exceptions_index[call] = [exceptions_counter]
                exceptions[exceptions_counter] = entry
                exceptions_counter += 1
            else:
                if call in prefixes_index.keys():
                    prefixes_index[call].append(prefixes_counter)
                else:
                    prefixes_index[call] = [prefixes_counter]
                prefixes[prefixes_counter] = entry
                prefixes_counter += 1

        self._logger.debug(str(len(prefixes))+" Prefixes added")
        self._logger.debug(str(len(prefixes_index))+" Prefixes in Index")
        self._logger.debug(str(len(exceptions))+" Exceptions added")
        self._logger.debug(str(len(exceptions_index))+" Exceptions in Index")

        result = {
            "prefixes" : prefixes,
            "exceptions" : exceptions,
            "prefixes_index" : prefixes_index,
            "exceptions_index" : exceptions_index,
        }

        return result

    def _generate_random_word(self, length):
        """
            Generates a random word
        """
        return ''.join(random.choice(string.lowercase) for i in xrange(length))

    def _check_html_response(self, response):
        """
            Checks if the API Key is valid and if the request returned a 200 status (ok)
        """

        error1 = "Access to this form requires a valid API key. For more info see: http://www.clublog.org/need_api.php"
        error2 = "Invalid or missing API Key"

        if response.status_code == requests.codes.ok:
            return True
        else:
            self._logger.error("HTTP Repsonse: " + str(response.text))
            if response.text.strip() == error1 or response.text.strip() == error2:
                raise APIKeyMissingError
            else:
                raise LookupError