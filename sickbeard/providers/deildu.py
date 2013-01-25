# Author: Trymbill <@trymbill>
# URL: http://code.google.com/p/sickbeard/
#
# This file is part of Sick Beard.
#
# Sick Beard is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Sick Beard is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Sick Beard.  If not, see <http://www.gnu.org/licenses/>.

import re
import urllib, urllib2
import cookielib
import sys
import os

import sickbeard
import generic
from sickbeard.common import Quality
from sickbeard.name_parser.parser import NameParser, InvalidNameException
from sickbeard import logger
from sickbeard import tvcache
from sickbeard import helpers
from sickbeard import show_name_helpers
from sickbeard.common import Overview 
from sickbeard.exceptions import ex
from sickbeard import encodingKludge as ek

cookie_filename = "deildu.cookies"

class DeilduLoginHandler(object):

    def __init__(self, login, password):
        """ Start up... """
        self.login = login
        self.password = password

        self.cj = cookielib.MozillaCookieJar(cookie_filename)
        # check if we can access cookie, and make sure it's not empty
        if os.access(cookie_filename, os.F_OK) and os.path.getsize(cookie_filename) > 0:
            self.cj.load()
        self.opener = urllib2.build_opener(
            urllib2.HTTPRedirectHandler(),
            urllib2.HTTPHandler(debuglevel=0),
            urllib2.HTTPSHandler(debuglevel=0),
            urllib2.HTTPCookieProcessor(self.cj)
        )
        self.opener.addheaders = [
            ('User-agent', ('Mozilla/4.0 (compatible; MSIE 6.0; '
                           'Windows NT 5.2; .NET CLR 1.1.4322)'))
        ]

        # need this twice - once to set cookies, once to log in...
        self.loginToDeildu()
        self.loginToDeildu()

        self.cj.save()

    def loginToDeildu(self):
        """
        Handle login. This should populate our cookie jar.
        """
        login_data = urllib.urlencode({
            'username' : self.login,
            'password' : self.password,
        })
        response = self.opener.open("http://deildu.net/takelogin.php", login_data)
        logger.log('Logged in to Deildu.net',logger.DEBUG)
        return response

    def loggedIn(self):
        # TODO: Check if user actually got logged in
        return True

class DeilduProvider(generic.TorrentProvider):

    def __init__(self):

        generic.TorrentProvider.__init__(self, "Deildu")
        
        self.supportsBacklog = True
        self.cache = DeilduCache(self)
        self.url = 'http://deildu.net/'

        self.searchurl = self.url+'browse.php?cat=0&search=%s&sort=seeders&type=desc'
        self.re_title_url = '<tr>.*?browse\.php.*?details\.php\?id=(?P<id>\d+).+?<b>(?P<title>.*?)</b>.+?class=\"index\" href=\"(?P<url>.*?)".+?sinnum.+?align=\"right\">(?P<seeders>.*?)</td>.*?align=\"right\">(?P<leechers>.*?)</td>.*?</tr>'

    def isEnabled(self):
        return sickbeard.DEILDU
        
    def imageName(self):
        return 'deildu.png'
    
    def getQuality(self, item):
        
        quality = Quality.nameQuality(item[0])
        return quality

    def _reverseQuality(self,quality):

        quality_string = ''

        if quality == Quality.SDTV:
            quality_string = 'HDTV x264'
        elif quality == Quality.HDTV:    
            quality_string = '720p HDTV x264'
        elif quality == Quality.HDWEBDL:
            quality_string = '720p WEB-DL'
        elif quality == Quality.HDBLURAY:
            quality_string = '720p Bluray x264'
        elif quality == Quality.FULLHDBLURAY:
            quality_string = '1080p Bluray x264'  
        
        return quality_string

    def _find_season_quality(self,title,torrent_id):
        """ Return the modified title of a Season Torrent with the quality found inspecting torrent file list """

        mediaExtensions = ['avi', 'mkv', 'wmv', 'divx',
                           'vob', 'dvr-ms', 'wtv', 'ts'
                           'ogv', 'rar', 'zip'] 
        
        quality = Quality.UNKNOWN        
        
        fileName = None
        
        fileURL = self.url+'ajax_details_filelist.php?id='+str(torrent_id)
      
        data = self.getURL(fileURL)
        
        if not data:
            return None
        
        filesList = re.findall('<td.+>(.*?)</td>',data) 
        
        if not filesList: 
            logger.log(u"Unable to get the torrent file list for "+title, logger.ERROR)
            
        for fileName in filter(lambda x: x.rpartition(".")[2].lower() in mediaExtensions, filesList):
            quality = Quality.nameQuality(os.path.basename(fileName))
            if quality != Quality.UNKNOWN: break

        if fileName!=None and quality == Quality.UNKNOWN:
            quality = Quality.assumeQuality(os.path.basename(fileName))            

        if quality == Quality.UNKNOWN:
            logger.log(u"No Season quality for "+title, logger.DEBUG)
            return None

        try:
            myParser = NameParser()
            parse_result = myParser.parse(fileName)
        except InvalidNameException:
            return None
        
        logger.log(u"Season quality for "+title+" is "+Quality.qualityStrings[quality], logger.DEBUG)
        
        if parse_result.series_name and parse_result.season_number: 
            title = parse_result.series_name+' S%02d' % int(parse_result.season_number)+' '+self._reverseQuality(quality)
        
        return title

    def _get_season_search_strings(self, show, season=None):

        search_string = {'Episode': []}
    
        if not show:
            return []

        seasonEp = show.getAllEpisodes(season)

        wantedEp = [x for x in seasonEp if show.getOverview(x.status) in (Overview.WANTED, Overview.QUAL)]          

        #If Every episode in Season is a wanted Episode then search for Season first
        if wantedEp == seasonEp:
            search_string = {'Season': [], 'Episode': []}
            for show_name in set(show_name_helpers.allPossibleShowNames(show)):
                ep_string = show_name +' S%02d' % int(season) #1) ShowName SXX   
                search_string['Season'].append(ep_string)
                      
                ep_string = show_name+' Season '+str(season) #2) ShowName Season X  
                search_string['Season'].append(ep_string)

        #Building the search string with the episodes we need         
        for ep_obj in wantedEp:
            search_string['Episode'] += self._get_episode_search_strings(ep_obj)[0]['Episode']
        
        #If no Episode is needed then return an empty list
        if not search_string['Episode']:
            return []
        
        return [search_string]

    def _get_episode_search_strings(self, ep_obj):
       
        search_string = {'Episode': []}
       
        if not ep_obj:
            return []
                
        if ep_obj.show.air_by_date:
            for show_name in set(show_name_helpers.allPossibleShowNames(ep_obj.show)):
                ep_string = show_name_helpers.sanitizeSceneName(show_name) +' '+ str(ep_obj.airdate)
                search_string['Episode'].append(ep_string)
        else:
            for show_name in set(show_name_helpers.allPossibleShowNames(ep_obj.show)):
                ep_string = show_name_helpers.sanitizeSceneName(show_name) +' '+ \
                sickbeard.config.naming_ep_type[2] % {'seasonnumber': ep_obj.season, 'episodenumber': ep_obj.episode}

                search_string['Episode'].append(ep_string)
    
        return [search_string]

    def _doSearch(self, search_params, show=None):
    
        results = []
        items = {'Season': [], 'Episode': []}

        for mode in search_params.keys():
            for search_string in search_params[mode]:

                searchURL = self.searchurl % (urllib.quote(search_string))
                logger.log(u"Search string: " + searchURL, logger.DEBUG)
        
                # make sure we've got a cookie ready to use deildu.net
                dlh = DeilduLoginHandler(sickbeard.DEILDU_USERNAME, sickbeard.DEILDU_PASSWORD)
                if not dlh.loggedIn():
                    logger.log("User or pass for Deildu.net not correct", logger.ERROR)
                    return []

                logger.log('Got cookie from Deildu', logger.DEBUG)

                # get the browse url with the cookiejar provided to get in
                data = self.getURL(searchURL, dlh.cj)
                if not data or 'login' in data:
                    logger.log("Login handler failed, login form or nothing returned", logger.ERROR)
                    return []

                # a crude way of checking if deildu returned no results
                if 'Ekkert fannst!' in data:
                    logger.log("Deildu reported that no torrent was found", logger.MESSAGE)
                    return []
                
                #Extracting torrent information from data returned by searchURL                   
                match = re.compile(self.re_title_url, re.DOTALL).finditer(urllib.unquote(data))

                for torrent in match:

                    title = torrent.group('title').replace('_','.').decode('iso-8859-1')
                    url = torrent.group('url')
                    id = int(torrent.group('id'))
                    seeders = int(re.sub('<[^<]+?>', '', torrent.group('seeders')))
                    leechers = int(re.sub('<[^<]+?>', '', torrent.group('leechers')))

                    #Filter unseeded torrent
                    if seeders == 0:
                        continue
                       
                    if not show_name_helpers.filterBadReleases(title):
                        continue

                    #Try to find the real Quality for full season torrent analyzing files in torrent 
                    if mode == 'Season' and Quality.nameQuality(title) == Quality.UNKNOWN:
                        title = self._find_season_quality(title,id)
                    
                    if not title:
                        continue
                        
                    item = title, self.url+url, id, seeders, leechers
                    items[mode].append(item)

            #For each search mode sort all the items by seeders
            items[mode].sort(key=lambda tup: tup[3], reverse=True)

            results += items[mode]
                
        return results

    def _get_title_and_url(self, item):
        
        title, url, id, seeders, leechers = item
        
        if url:
            url = url.replace('&amp;','&')

        return (title, url)

    def getURL(self, url, cj=None):
            
        result = None

        try:
            result = helpers.getURL(url, [], cj)
        except (urllib2.HTTPError, IOError), e:
            logger.log(u"Error loading "+self.name+" URL: " + str(sys.exc_info()) + " - " + ex(e), logger.ERROR)
            return None

        return result

class DeilduCache(tvcache.TVCache):

    def __init__(self, provider):

        tvcache.TVCache.__init__(self, provider)

        # only poll Deildu every 10 minutes max
        self.minTime = 10

    def updateCache(self):

        re_title_url = self.provider.re_title_url
                
        if not self.shouldUpdate():
            return

        data = self._getData()

        # as long as the http request worked we count this as an update
        if data:
            self.setLastUpdate()
        else:
            return []

        # now that we've loaded the current Deildu data lets delete the old cache
        logger.log(u"Clearing "+self.provider.name+" cache and updating with new information")
        self._clearCache()

        match = re.compile(re_title_url, re.DOTALL).finditer(urllib.unquote(data))
        if not match:
            logger.log(u"The Data returned from Deildu is incomplete, this result is unusable", logger.ERROR)
            return []
                
        for torrent in match:

            title = torrent.group('title').replace('_','.')#Do not know why but SickBeard skip release with '_' in name
            url = torrent.group('url')
           
            item = (title,url)

            self._parseItem(item)

    def _getData(self):
       
        #url for the last 50 tv-show
        url = self.provider.url+'browse.php?c12=1&c8=1&incldead=0'
        logger.log(u"Deildu cache update URL: "+ url, logger.DEBUG)

        data = self.provider.getURL(url)
        return data

    def _parseItem(self, item):

        (title, url) = item

        if not title or not url:
            return

        logger.log(u"Adding item to cache: "+title, logger.DEBUG)

        self._addCacheEntry(title, url)
    
provider = DeilduProvider()
