# Gallery Image Management — Implementation Notes

## Setup
1. `pip install -r requirements.txt --break-system-packages` (adds `Pillow`, needed for
   image uploads/auto-resizing).
2. `python manage.py migrate` (applies `booking/migrations/0011_galleryimage.py`).
3. That's it — no manual folder setup needed. Django creates the `media/` folder on disk
   automatically the first time a photo is uploaded.

## How it works

**Where to add photos:** Log into Django Admin (`/admin/`) → **Gallery Images** → **Add**.
There's also a direct "🖼️ Add Gallery Photo" button on the main staff dashboard, and a
"🖼️ Gallery" link in the dashboard sidebar, for one-click access without hunting through
Django Admin's menu.

**What you set per photo:**
- The image file itself
- Category (Weddings / Birthdays / Corporate / Beach / School / Festival / Setup) - this
  must match one of the filter tabs on the public Gallery page for the photo to show up
  when that tab is clicked
- An optional caption (shown as the small tag overlay on the photo; falls back to the
  category name if left blank)
- Display order (lower numbers show first; ties break newest-first)
- Active/inactive (uncheck to hide a photo without deleting it)

**Automatic optimization:** every upload is automatically re-encoded to a max of 1600px on
its long edge and saved as an 85%-quality JPEG (see `GalleryImage.save()` in `models.py`).
This is what stops a 12MB photo straight off someone's phone from being served at full size
to every visitor. It also auto-corrects photo orientation (phones often save rotation as
metadata rather than actually rotating the pixels, which without this fix can result in
sideways photos on the web). If Pillow can't process a given file for any reason, the
original upload is kept as-is rather than blocking the save.

**Public page:** `templates/booking/gallery.html`'s hardcoded placeholder photos were
replaced with a loop over `GalleryImage.objects.filter(is_active=True)` (see
`views.gallery`). The existing tab-filter JavaScript (`static/js/gallery.js`) didn't need
any changes — it already filters by a `data-category` attribute, which now comes from the
database instead of being hardcoded. If there are zero active photos, the page shows a
friendly "check back soon" message with an Instagram link instead of an empty grid.

## Production note
`MEDIA_URL`/`MEDIA_ROOT` are now configured in `settings.py`, and `decisivesounds/urls.py`
serves them automatically **only when `DEBUG=True`** (Django's own recommendation — its dev
server isn't meant for production traffic). Once you deploy this for real, uploaded photos
need to be served another way — either your production web server (e.g. an nginx location
block pointing at `MEDIA_ROOT`) or, better for durability across deploys, object storage like
S3/Cloudinary via `django-storages`. Until that's set up, gallery photos uploaded on a
production host that gets redeployed/redeployed-to-ephemeral-disk could be lost - worth
flagging to whoever handles deployment.
