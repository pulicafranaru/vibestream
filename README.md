# VibeStream

A self-hosted media server with its own apps. You pick a film or a show, the
server fetches it, prepares it for streaming, and everyone in the house watches
it on the TV, in a browser, or on an iPhone, iPad or Android phone, each with
their own profile, resume positions and ratings.

![The web app's home page](docs/screenshots/web-home.jpg)

## What it does

- **A catalog that is already full.** A new server starts with about 4,300
  films and 700 shows, with their seasons and episodes, and keeps it current
  from TMDB.
- **Releases from where you have access.** A FileList account, or any Stremio
  addon (Torrentio, Comet, MediaFusion, or one set up with a debrid service),
  or both. Each version of a title shows where it came from.
- **One button.** Download becomes Downloading, then Preparing, then Play.
  Files are fetched by qBittorrent, or over HTTPS from a debrid service when an
  addon offers a link, then hardlinked into a tidy library.
- **A player of its own.** HLS with the video passed through untouched (4K, HDR
  and Dolby Vision play on the TV and on Apple devices), subtitles drawn by the
  app, seek thumbnails, audio track choice, and casting between devices.
- **Housekeeping.** Watched titles are cleaned up after a grace period,
  respecting seeding rules, and the dashboard shows disk use, jobs and health.

| Client | Source | Runs on |
| --- | --- | --- |
| Web and TV | `web/` (React) | any browser; LG webOS TVs through the launcher in `webos/` |
| iOS and iPadOS | `ios/` (SwiftUI) | iPhone and iPad |
| Android (experimental) | `android/` (Jetpack Compose) | phones and tablets |

## Screenshots

### Web

| | |
| --- | --- |
| ![A title page](docs/screenshots/web-title.jpg) | ![Versions of a film, with where each came from](docs/screenshots/web-versions.jpg) |
| ![The player](docs/screenshots/web-player.jpg) | ![Search](docs/screenshots/web-search.jpg) |

### TV

![The TV app on an LG webOS set](docs/screenshots/tv-home.jpg)

### iPhone and iPad

<p>
<img src="docs/screenshots/iphone-profiles.jpg" width="19%" alt="Profiles">
<img src="docs/screenshots/iphone-home.jpg" width="19%" alt="Home">
<img src="docs/screenshots/iphone-title.jpg" width="19%" alt="A show">
<img src="docs/screenshots/iphone-movie.jpg" width="19%" alt="A film">
<img src="docs/screenshots/iphone-search.jpg" width="19%" alt="Search">
</p>

<p>
<img src="docs/screenshots/iphone-player.jpg" width="56%" alt="The player">
<img src="docs/screenshots/ipad-home.jpg" width="20%" alt="Home on iPad">
<img src="docs/screenshots/ipad-title.jpg" width="20%" alt="A show on iPad">
</p>

### Android (experimental)

<p>
<img src="docs/screenshots/android-profiles.jpg" width="24%" alt="Profiles">
<img src="docs/screenshots/android-home.jpg" width="24%" alt="Home">
<img src="docs/screenshots/android-title.jpg" width="24%" alt="A show">
<img src="docs/screenshots/android-movie.jpg" width="24%" alt="A film">
</p>

### Dashboard

| | |
| --- | --- |
| ![The dashboard's overview](docs/screenshots/admin-overview.jpg) | ![Sources](docs/screenshots/admin-sources.jpg) |

Shown with *Night of the Living Dead* (1968), which is in the public domain.
Posters and artwork come from TMDB.

## Install

On a Linux machine (x86_64 or arm64) with room for media:

```bash
curl -fsSL https://raw.githubusercontent.com/pulicafranaru/vibestream/main/install.sh | sudo bash
```

The installer sets up Docker if needed, asks where films and shows should be
kept, starts VibeStream and qBittorrent under `/opt/vibestream`, and prints the
address and a one-time setup code. Open `/admin` at that address, enter the
code, choose an admin password, and the setup walks you through:

1. **Where releases come from:** a FileList username and passkey, or the
   address of a Stremio addon (Torrentio is filled in).
2. **TMDB:** a free API key from themoviedb.org, for posters and details.
3. **Subtitles:** the languages to keep.

Run the same command again to update. Settings, media and the database are kept.

Installer options, as environment variables: `VIBESTREAM_DIR`,
`VIBESTREAM_MEDIA`, `VIBESTREAM_PORT` (80 when free, otherwise 8100),
`VIBESTREAM_IMAGE`, `VIBESTREAM_NAME` and `TORRENT_PORT`.

## Security

VibeStream is built for a home network. The dashboard at `/admin` needs the
admin password, and profiles can have a PIN, but browsing the catalog and
starting downloads needs no sign-in. Do not expose the server directly to the
internet. To watch away from home, use a VPN to your network.

## Sources

### FileList

Enter the username and the passkey from your FileList profile page. New
releases are swept every hour, and a search for something the sweep has not
seen asks FileList directly. FileList releases are preferred to public ones at
the same resolution.

### Stremio addons

Sources accepts any Stremio addon address, exactly as the addon's configure
page gives it. Every addon is asked about a title when it is opened or
searched for, and about the week's trending titles twice a day.

With a debrid service (Real-Debrid, AllDebrid, TorBox and the like) set up in
the addon, films and single episodes the service already holds are fetched
from it over HTTPS at full speed, with no torrent client involved. The
dashboard shows addon addresses hidden, since they carry the service's key.

Public torrents show your server's address to everyone sharing them.

## Apps

The web app needs nothing: open the server's address. The others are built from
this repository. Copy `.env.example` to `.env` and fill in the app section.

- **iOS and iPadOS:** Xcode and `brew install xcodegen`, then
  `scripts/deploy-ios.sh`. Needs `APPLE_TEAM_ID`, `APP_ID` and the devices in
  `IOS_DEVICES`.
- **Android (experimental):** not complete yet. Some screens and features of
  the iOS app are still missing, and it is less tested. Needs JDK 17 and the
  Android command line tools, then `scripts/deploy-android.sh` with a device
  connected over USB debugging.
- **LG webOS TVs:** `scripts/deploy-tv.sh` packages the launcher and installs it
  over SSH on TVs listed in `TV_HOSTS`. The TV loads the app from the server, so
  interface updates need no reinstall.

Each app finds the server from `PUBLIC_URL` and `LAN_URL` in `.env`.

## Development

```bash
cd api && python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q

cd web && npm ci && npm run build
```

The server is FastAPI with SQLite (`api/vibestream`), the front ends are in
`web/src` (`web/` for browsers, `tv/` for TVs, `admin/` for the dashboard,
`shared/` for both). The container image is built by
`.github/workflows/image.yml` for x86_64 and arm64.

## Third-party material

- Figtree, by Erik Kennedy, under the SIL Open Font License
  (`web/src/shared/fonts/OFL.txt`).
- The YOLO11n detection and pose models in `api/vibestream/assets/`, by
  Ultralytics, under AGPL-3.0, used to aim the tall frame of a
  clip's vertical version at the people and things in it.
- Metadata and images from TMDB. This product uses the TMDB API but is not
  endorsed or certified by TMDB.

## License

VibeStream is free software under the GNU Affero General Public License,
version 3 (`LICENSE`). If you run a modified version for other people over a
network, you must offer them its source.
