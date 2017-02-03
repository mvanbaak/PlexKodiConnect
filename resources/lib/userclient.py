# -*- coding: utf-8 -*-

###############################################################################
import logging
import threading

import xbmc
import xbmcgui
import xbmcaddon
import xbmcvfs

from utils import window, settings, language as lang, ThreadMethods, \
    tryDecode, ThreadMethodsAdditionalSuspend
import downloadutils

import PlexAPI
from PlexFunctions import GetMachineIdentifier

###############################################################################

log = logging.getLogger("PLEX."+__name__)

###############################################################################


@ThreadMethodsAdditionalSuspend('suspend_Userclient')
@ThreadMethods
class UserClient(threading.Thread):

    # Borg - multiple instances, shared state
    __shared_state = {}

    def __init__(self, callback=None):
        self.__dict__ = self.__shared_state
        if callback is not None:
            self.mgr = callback

        self.auth = True
        self.retry = 0

        self.currUser = None
        self.currUserId = None
        self.currServer = None
        self.currToken = None
        self.HasAccess = True
        self.AdditionalUser = []

        self.userSettings = None

        self.addon = xbmcaddon.Addon()
        self.doUtils = downloadutils.DownloadUtils()

        threading.Thread.__init__(self)

    def getUsername(self):
        """
        Returns username as unicode
        """
        username = settings('username')
        if not username:
            log.debug("No username saved, trying to get Plex username")
            username = settings('plexLogin')
            if not username:
                log.debug("Also no Plex username found")
                return ""
        return username

    def getServer(self, prefix=True):
        # Original host
        self.servername = settings('plex_servername')
        HTTPS = settings('https') == "true"
        host = settings('ipaddress')
        port = settings('port')
        self.machineIdentifier = settings('plex_machineIdentifier')

        server = host + ":" + port

        if not host:
            log.debug("No server information saved.")
            return False

        # If https is true
        if prefix and HTTPS:
            server = "https://%s" % server
        # If https is false
        elif prefix and not HTTPS:
            server = "http://%s" % server
        # User entered IP; we need to get the machineIdentifier
        if self.machineIdentifier == '' and prefix is True:
            self.machineIdentifier = GetMachineIdentifier(server)
            if self.machineIdentifier is None:
                self.machineIdentifier = ''
            settings('plex_machineIdentifier', value=self.machineIdentifier)
        log.debug('Returning active server: %s' % server)
        return server

    def getSSLverify(self):
        # Verify host certificate
        return None if settings('sslverify') == 'true' else False

    def getSSL(self):
        # Client side certificate
        return None if settings('sslcert') == 'None' \
            else settings('sslcert')

    def setUserPref(self):
        log.debug('Setting user preferences')
        # Only try to get user avatar if there is a token
        if self.currToken:
            url = PlexAPI.PlexAPI().GetUserArtworkURL(self.currUser)
            if url:
                window('PlexUserImage', value=url)
        # Set resume point max
        # url = "{server}/emby/System/Configuration?format=json"
        # result = doUtils.downloadUrl(url)

    def hasAccess(self):
        # Plex: always return True for now
        return True
        # hasAccess is verified in service.py
        url = "{server}/emby/Users?format=json"
        result = self.doUtils.downloadUrl(url)

        if result is False:
            # Access is restricted, set in downloadutils.py via exception
            log.info("Access is restricted.")
            self.HasAccess = False

        elif window('plex_online') != "true":
            # Server connection failed
            pass

        elif window('plex_serverStatus') == "restricted":
            log.info("Access is granted.")
            self.HasAccess = True
            window('plex_serverStatus', clear=True)
            xbmcgui.Dialog().notification(lang(29999),
                                          lang(33007))

    def loadCurrUser(self, username, userId, usertoken, authenticated=False):
        log.debug('Loading current user')
        doUtils = self.doUtils

        self.currUserId = userId
        self.currToken = usertoken
        self.currServer = self.getServer()
        self.ssl = self.getSSLverify()
        self.sslcert = self.getSSL()

        if authenticated is False:
            log.debug('Testing validity of current token')
            res = PlexAPI.PlexAPI().CheckConnection(self.currServer,
                                                    token=self.currToken,
                                                    verifySSL=self.ssl)
            if res is False:
                # PMS probably offline
                return False
            elif res == 401:
                log.error('Token is no longer valid')
                return 401
            elif res >= 400:
                log.error('Answer from PMS is not as expected. Retrying')
                return False

        # Set to windows property
        window('currUserId', value=userId)
        window('plex_username', value=username)
        # This is the token for the current PMS (might also be '')
        window('pms_token', value=self.currToken)
        # This is the token for plex.tv for the current user
        # Is only '' if user is not signed in to plex.tv
        window('plex_token', value=settings('plexToken'))
        window('plex_restricteduser', value=settings('plex_restricteduser'))
        window('pms_server', value=self.currServer)
        window('plex_machineIdentifier', value=self.machineIdentifier)
        window('plex_servername', value=self.servername)
        window('plex_authenticated', value='true')

        window('useDirectPaths', value='true'
               if settings('useDirectPaths') == "1" else 'false')
        window('plex_force_transcode_pix', value='true'
               if settings('force_transcode_pix') == "1" else 'false')

        # Start DownloadUtils session
        doUtils.startSession(reset=True)
        # self.getAdditionalUsers()
        # Set user preferences in settings
        self.currUser = username
        self.setUserPref()

        # Writing values to settings file
        settings('username', value=username)
        settings('userid', value=userId)
        settings('accessToken', value=usertoken)
        return True

    def authenticate(self):
        log.debug('Authenticating user')
        dialog = xbmcgui.Dialog()

        # Give attempts at entering password / selecting user
        if self.retry >= 2:
            log.error("Too many retries to login.")
            window('plex_serverStatus', value="Stop")
            dialog.ok(lang(33001),
                      lang(39023))
            xbmc.executebuiltin(
                'Addon.OpenSettings(plugin.video.plexkodiconnect)')
            return False

        # Get /profile/addon_data
        addondir = tryDecode(xbmc.translatePath(
            self.addon.getAddonInfo('profile')))
        hasSettings = xbmcvfs.exists("%ssettings.xml" % addondir)

        # If there's no settings.xml
        if not hasSettings:
            log.error("Error, no settings.xml found.")
            self.auth = False
            return False
        server = self.getServer()
        # If there is no server we can connect to
        if not server:
            log.info("Missing server information.")
            self.auth = False
            return False

        # If there is a username in the settings, try authenticating
        username = settings('username')
        userId = settings('userid')
        usertoken = settings('accessToken')
        enforceLogin = settings('enforceUserLogin')
        # Found a user in the settings, try to authenticate
        if username and enforceLogin == 'false':
            log.debug('Trying to authenticate with old settings')
            answ = self.loadCurrUser(username,
                                     userId,
                                     usertoken,
                                     authenticated=False)
            if answ is True:
                # SUCCESS: loaded a user from the settings
                return True
            elif answ == 401:
                log.error("User token no longer valid. Sign user out")
                settings('username', value='')
                settings('userid', value='')
                settings('accessToken', value='')
            else:
                log.debug("Could not yet authenticate user")
                return False

        plx = PlexAPI.PlexAPI()

        # Could not use settings - try to get Plex user list from plex.tv
        plextoken = settings('plexToken')
        if plextoken:
            log.info("Trying to connect to plex.tv to get a user list")
            userInfo = plx.ChoosePlexHomeUser(plextoken)
            if userInfo is False:
                # FAILURE: Something went wrong, try again
                self.auth = True
                self.retry += 1
                return False
            username = userInfo['username']
            userId = userInfo['userid']
            usertoken = userInfo['token']
        else:
            log.info("Trying to authenticate without a token")
            username = ''
            userId = ''
            usertoken = ''

        if self.loadCurrUser(username, userId, usertoken, authenticated=False):
            # SUCCESS: loaded a user from the settings
            return True
        else:
            # FAILUR: Something went wrong, try again
            self.auth = True
            self.retry += 1
            return False

    def resetClient(self):
        log.debug("Reset UserClient authentication.")
        self.doUtils.stopSession()

        window('plex_authenticated', clear=True)
        window('pms_token', clear=True)
        window('plex_token', clear=True)
        window('pms_server', clear=True)
        window('plex_machineIdentifier', clear=True)
        window('plex_servername', clear=True)
        window('currUserId', clear=True)
        window('plex_username', clear=True)
        window('plex_restricteduser', clear=True)

        settings('username', value='')
        settings('userid', value='')
        settings('accessToken', value='')

        # Reset token in downloads
        self.doUtils.setToken('')
        self.doUtils.setUserId('')
        self.doUtils.setUsername('')

        self.currToken = None
        self.auth = True
        self.currUser = None
        self.currUserId = None

        self.retry = 0

    def run(self):
        log.info("----===## Starting UserClient ##===----")
        while not self.threadStopped():
            while self.threadSuspended():
                if self.threadStopped():
                    break
                xbmc.sleep(1000)

            status = window('plex_serverStatus')

            if status == "Stop":
                xbmc.sleep(500)
                continue

            # Verify the connection status to server
            elif status == "restricted":
                # Parental control is restricting access
                self.HasAccess = False

            elif status == "401":
                # Unauthorized access, revoke token
                window('plex_serverStatus', value="Auth")
                self.resetClient()
                xbmc.sleep(2000)

            if self.auth and (self.currUser is None):
                # Try to authenticate user
                if not status or status == "Auth":
                    # Set auth flag because we no longer need
                    # to authenticate the user
                    self.auth = False
                    if self.authenticate():
                        # Successfully authenticated and loaded a user
                        log.info("Successfully authenticated!")
                        log.info("Current user: %s" % self.currUser)
                        log.info("Current userId: %s" % self.currUserId)
                        self.retry = 0
                        window('suspend_LibraryThread', clear=True)
                        window('plex_serverStatus', clear=True)

            if not self.auth and (self.currUser is None):
                # Loop if no server found
                server = self.getServer()

                # The status Stop is for when user cancelled password dialog.
                # Or retried too many times
                if server and status != "Stop":
                    # Only if there's information found to login
                    log.debug("Server found: %s" % server)
                    self.auth = True

            # Minimize CPU load
            xbmc.sleep(100)

        self.doUtils.stopSession()
        log.info("##===---- UserClient Stopped ----===##")
