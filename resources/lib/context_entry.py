# -*- coding: utf-8 -*-

###############################################################################

import logging

import xbmc
import xbmcaddon

import plexdb_functions as plexdb
from utils import window, settings, dialog, language as lang, kodiSQL
from dialogs import context
from PlexFunctions import delete_item_from_pms
import variables as v

###############################################################################

log = logging.getLogger("PLEX."+__name__)

OPTIONS = {
    'Refresh': lang(30410),
    'Delete': lang(30409),
    'Addon': lang(30408),
    # 'AddFav': lang(30405),
    # 'RemoveFav': lang(30406),
    # 'RateSong': lang(30407),
    'Transcode': lang(30412),
    'PMS_Play': lang(30415)  # Use PMS to start playback
}

###############################################################################


class ContextMenu(object):

    _selected_option = None

    def __init__(self):
        self.kodi_id = xbmc.getInfoLabel('ListItem.DBID').decode('utf-8')
        self.item_type = self._get_item_type()
        self.item_id = self._get_item_id(self.kodi_id, self.item_type)

        log.info("Found item_id: %s item_type: %s"
                 % (self.item_id, self.item_type))

        if not self.item_id:
            return

        if self._select_menu():
            self._action_menu()

            if self._selected_option in (OPTIONS['Delete'],
                                         OPTIONS['Refresh']):
                log.info("refreshing container")
                xbmc.sleep(500)
                xbmc.executebuiltin('Container.Refresh')

    @classmethod
    def _get_item_type(cls):
        item_type = xbmc.getInfoLabel('ListItem.DBTYPE').decode('utf-8')
        if not item_type:
            if xbmc.getCondVisibility('Container.Content(albums)'):
                item_type = "album"
            elif xbmc.getCondVisibility('Container.Content(artists)'):
                item_type = "artist"
            elif xbmc.getCondVisibility('Container.Content(songs)'):
                item_type = "song"
            elif xbmc.getCondVisibility('Container.Content(pictures)'):
                item_type = "picture"
            else:
                log.info("item_type is unknown")
        return item_type

    @classmethod
    def _get_item_id(cls, kodi_id, item_type):
        item_id = xbmc.getInfoLabel('ListItem.Property(plexid)')
        if not item_id and kodi_id and item_type:
            with plexdb.Get_Plex_DB() as plexcursor:
                item = plexcursor.getItem_byKodiId(kodi_id, item_type)
            try:
                item_id = item[0]
            except TypeError:
                log.error('Could not get the Plex id for context menu')
        return item_id

    def _select_menu(self):
        # Display select dialog
        options = []

        # if user uses direct paths, give option to initiate playback via PMS
        if (window('useDirectPaths') == 'true' and
                self.item_type in v.KODI_VIDEOTYPES):
            options.append(OPTIONS['PMS_Play'])

        if self.item_type in v.KODI_VIDEOTYPES:
            options.append(OPTIONS['Transcode'])

        # userdata = self.api.getUserData()
        # if userdata['Favorite']:
        #     # Remove from emby favourites
        #     options.append(OPTIONS['RemoveFav'])
        # else:
        #     # Add to emby favourites
        #     options.append(OPTIONS['AddFav'])

        # if self.item_type == "song":
        #     # Set custom song rating
        #     options.append(OPTIONS['RateSong'])

        # Refresh item
        # options.append(OPTIONS['Refresh'])
        # Delete item, only if the Plex Home main user is logged in
        if (window('plex_restricteduser') != 'true' and
                window('plex_allows_mediaDeletion') == 'true'):
            options.append(OPTIONS['Delete'])
        # Addon settings
        options.append(OPTIONS['Addon'])

        context_menu = context.ContextMenu(
            "script-emby-context.xml",
            xbmcaddon.Addon(
                'plugin.video.plexkodiconnect').getAddonInfo('path'),
            "default", "1080i")
        context_menu.set_options(options)
        context_menu.doModal()

        if context_menu.is_selected():
            self._selected_option = context_menu.get_selected()

        return self._selected_option

    def _action_menu(self):

        selected = self._selected_option

        if selected == OPTIONS['Transcode']:
            window('plex_forcetranscode', value='true')
            self._PMS_play()

        elif selected == OPTIONS['PMS_Play']:
            self._PMS_play()

        # elif selected == OPTIONS['Refresh']:
        #     self.emby.refreshItem(self.item_id)

        # elif selected == OPTIONS['AddFav']:
        #     self.emby.updateUserRating(self.item_id, favourite=True)

        # elif selected == OPTIONS['RemoveFav']:
        #     self.emby.updateUserRating(self.item_id, favourite=False)

        # elif selected == OPTIONS['RateSong']:
        #     self._rate_song()

        elif selected == OPTIONS['Addon']:
            xbmc.executebuiltin('Addon.OpenSettings(plugin.video.plexkodiconnect)')

        elif selected == OPTIONS['Delete']:
            self._delete_item()

    def _rate_song(self):

        conn = kodiSQL('music')
        cursor = conn.cursor()
        query = "SELECT rating FROM song WHERE idSong = ?"
        cursor.execute(query, (self.kodi_id,))
        try:
            value = cursor.fetchone()[0]
            current_value = int(round(float(value), 0))
        except TypeError:
            pass
        else:
            new_value = dialog("numeric", 0, lang(30411), str(current_value))
            if new_value > -1:

                new_value = int(new_value)
                if new_value > 5:
                    new_value = 5

                if settings('enableUpdateSongRating') == "true":
                    musicutils.updateRatingToFile(new_value, self.api.get_file_path())

                query = "UPDATE song SET rating = ? WHERE idSong = ?"
                cursor.execute(query, (new_value, self.kodi_id,))
                conn.commit()
        finally:
            cursor.close()

    def _delete_item(self):

        delete = True
        if settings('skipContextMenu') != "true":

            if not dialog("yesno", heading=lang(29999), line1=lang(33041)):
                log.info("User skipped deletion for: %s", self.item_id)
                delete = False

        if delete:
            log.info("Deleting Plex item with id %s", self.item_id)
            if delete_item_from_pms(self.item_id) is False:
                dialog("ok", heading="{plex}", line1=lang(30414))

    def _PMS_play(self):
        """
        For using direct paths: Initiates playback using the PMS
        """
        window('plex_contextplay', value='true')
        params = {
            'filename': '/library/metadata/%s' % self.item_id,
            'id': self.item_id,
            'dbid': self.kodi_id,
            'mode': "play"
        }
        from urllib import urlencode
        handle = ("plugin://plugin.video.plexkodiconnect/movies?%s"
                  % urlencode(params))
        xbmc.executebuiltin('RunPlugin(%s)' % handle)
