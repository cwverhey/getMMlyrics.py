#!/usr/bin/env python3

import os
from sys import platform
from re import search
from glob import glob
from math import floor
from requests import get
from json import loads
from urllib.parse import quote, urlparse, parse_qs
from pprint import pp
from shutil import get_terminal_size

CACHEFOLDERS = ['~/Library/Application Support/Musixmatch/Cache/',
                '~/.config/Musixmatch/Cache/',
                '~/snap/musixmatch/current/.config/Musixmatch/Cache/',
                '~\\AppData\\Roaming\\Musixmatch\\Cache\\']

# get user credentials for musixmatch API
#
# - install the Musixmatch app
# - connect it with Spotify (or another player) and make it find at least one set of lyrics
# - get_mm_credentials() will search for your credentials in your Musixmatch cache files
#
# returns list [0: userblob_id, 1: user_language, 2: app_id, 3: usertoken, 4: guid, 5: signature]
#
def get_mm_credentials(cachefolders = CACHEFOLDERS, verbose = 1):

    # loop through cache files to look for credentials
    cachefiles = [glob(os.path.expanduser(f + '*')) for f in cachefolders]
    cachefiles = sum(cachefiles, [])
    cachefiles = filter(os.path.isfile, cachefiles)
    cachefiles = sorted(cachefiles, key=os.path.getmtime, reverse=True)
    for c in cachefiles:

        try:
            with open(c, 'rb') as file:
                c = file.read()
        except PermissionError:
            print(f'Unable to open {c}')
            if platform == 'win32': print('make sure Musixmatch is not running\n')
            continue

        m = search(b'(https://apic-desktop\.musixmatch\.com/ws/1\.1/macro\.subtitles\.get.*?)[^a-zA-Z0-9/#\?_=&%\.\-~]', c)
        if m:

            url = m.groups()[0].decode(errors='ignore')
            query = parse_qs(urlparse(url).query)

            credentials = []
            for p in ['userblob_id', 'user_language', 'app_id', 'usertoken', 'guid', 'signature']:
                credentials.append(query[p][0])

            break

    if not 'credentials' in locals():
        raise AttributeError(f'Unable to load credentials from "{CACHEFOLDERS}"')

    if verbose:
        print('Credentials:')
        print(credentials, end='\n\n')

    return credentials


# get lyrics from musixmatch
#
# input:
#   credentials: list [0: userblob_id, 1: user_language, 2: app_id, 3: usertoken, 4: guid, 5: signature]
#   title:       str song title eg. 'Another Brick in the Wall Part 1'
#   artist:      str song/album artist eg. 'Pink Floyd'
#   album:       str album title eg. 'The Wall'
#   spotify_id:  str spotify_id eg. 'spotify:track:4dfKz7RAHpo6ZCoCL8Rlrb'
#   length:      (float song length in seconds, int search margin in seconds) eg. (169.88, 2)
#   verbose:     int verbosity level (0/1/2)
#
# returns tuple (0: selection of most useful lyric info, 1: full response)
#
def get_mm_lyrics(creds, title = False, artist = False, album = False, spotify_id = False, length = False, verbose = 1):

    # create query parameters (in correct order)
    #
    # some potential other search parameters:
    # https://developer.musixmatch.com/documentation/api-reference/track-search
    # https://developer.musixmatch.com/documentation/api-reference/matcher-subtitle-get

    q = {}

    if length:
        q['f_subtitle_length'] = floor(length[0])  # The desired length of the subtitle (seconds)

    q['namespace'] = 'lyrics_synched'
    q['part'] = 'lyrics_crowd,user,lyrics_verified_by'

    if album:
        q['q_album'] = album   # The song album

    if artist:
        q['q_artist'] = artist  # The song artist
        q['q_artists'] = artist

    if length:
        q['q_duration'] = length[0]

    if title:
        q['q_track'] = title   # The song title

    q['tags'] = 'nowplaying'

    q['userblob_id'] = creds[0]
    q['user_language'] = creds[1]

    if spotify_id:
        q['track_spotify_id'] = spotify_id

    if length:
        q['f_subtitle_length_max_deviation'] = length[1]  # The maximum deviation allowed from the f_subtitle_length (seconds)

    q['subtitle_format'] = 'lrc'  # The format of the subtitle (mxm,lrc,dfxp,stledu). Default to mxm

    q['app_id'] = creds[2]
    q['usertoken'] = creds[3]
    q['guid'] = creds[4]
    q['signature'] = creds[5]
    q['signature_protocol'] = 'sha1'


    # HTTP GET request
    url = 'https://apic-desktop.musixmatch.com/ws/1.1/macro.subtitles.get?format=json'
    for k,v in q.items():
        if k != 'signature':
            v = quote(str(v))
        url += "&{}={}".format(k, v)

    headers = {'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Musixmatch/3.10.4043-master.20200211001 Chrome/83.0.4103.122 Electron/9.4.4 Safari/537.36',
               'cookie': 'mxm-encrypted-token='}

    r = get(url, headers=headers)


    if verbose:
        print('URL:\n'+url+'\n')


    if r.status_code != 200:
        if verbose: print(r.content)
        raise RuntimeError(f'\nHTTP GET returned with status {r.status_code}, url:\n{url}\n')


    # parse full JSON response
    full = loads(r.content.decode())

    if full['message']['header']['status_code'] != 200:
        if full['message']['header']['hint'] == 'captcha':
            raise RuntimeError('\nComplete the captcha at https://apic.musixmatch.com/captcha.html and then let Musixmatch store some fresh cache files by playing a few songs.\n')
        else:
            if verbose: pp(full)
            raise RuntimeError(f"\nJSON returned with status {full['message']['header']['status_code']}, url:\n{url}\n")

    if verbose >= 2:
        print('Full result:')
        pp(full, width=get_terminal_size((80,20))[0])
        print()


    # check if we have results
    if type(full['message']['body']['macro_calls']['matcher.track.get']['message']['body']) is str:
        raise ValueError("No results")


    # filter interesting info from matcher.track.get
    track = full['message']['body']['macro_calls']['matcher.track.get']['message']['body']['track']

    track_id = track['track_id']
    spotify_id = track['track_spotify_id']

    name   = track['track_name']
    length = track['track_length']
    artist = track['artist_name']
    album  = track['album_name']

    cover = [v for k,v in track.items() if 'album_coverart' in k and v != ''][-1]

    first_release = track['first_release_date'][:10]

    status = {'lyrics': bool(track['has_lyrics']),
              'crowd_lyrics': bool(track['has_lyrics_crowd']),
              'richsync': bool(track['has_richsync']),
              'subtitles': bool(track['has_subtitles']),
              'instrumental': bool(track['instrumental'])}


    # filter interesting info from track.lyrics.get
    lyrics_data = full['message']['body']['macro_calls']['track.lyrics.get']['message']['body']

    try:
        lyrics = lyrics_data['lyrics']['lyrics_body']
        language = lyrics_data['lyrics']['lyrics_language']
        copyright = lyrics_data['lyrics']['lyrics_copyright'].strip()
    except KeyError:
        lyrics = ''
        language = ''
        copyright = ''

    try:
        crowd_lyrics = [c['lyrics']['lyrics_body'] for c in lyrics_data['crowd_lyrics_list']]
    except KeyError:
        crowd_lyrics = []

    # filter interesting info from 'track.subtitles.get'
    subtitles_data = full['message']['body']['macro_calls']['track.subtitles.get']['message']['body']

    try:
        subtitles = [s['subtitle']['subtitle_body'] for s in subtitles_data['subtitle_list']]
    except (KeyError,TypeError):
        subtitles = []

    # pack data
    short = {}
    for k in ['track_id', 'spotify_id', 'name', 'artist', 'album', 'length',
              'cover', 'first_release', 'status', 'lyrics', 'language',
              'copyright', 'crowd_lyrics', 'subtitles']:
        short[k] = locals()[k]

    if verbose >= 1:
        print('Short result:')
        pp(short, width=get_terminal_size((80,20))[0])

    return(short, full)

if __name__ == '__main__':

    credentials = get_mm_credentials(verbose=0)

    #short, full = get_mm_lyrics(credentials, artist = 'Nightwish', title = 'Nemo')

    #short, full = get_mm_lyrics(credentials, title = 'Another Brick in the Wall Part 1', artist = 'Pink Floyd', length=(201.55, 5))

    short, full = get_mm_lyrics(credentials, artist = 'Fintroll', title = 'Trollhammaren')
