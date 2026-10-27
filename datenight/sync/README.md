# Setting up sync between your phones and laptop

Sync keeps everything the same on both iPhones and the laptop: logged dates, photos, edits and deletions, favourites, your own ideas, "said no to for good", your names, your anniversary and birthdays. A change on one device shows up on the others within a couple of minutes.

It uses your own free [Supabase](https://supabase.com) project as a shared online store. You set it up once, which takes about 5 minutes. No card is needed.

## 1. Create the Supabase project (once, on the laptop)

1. Go to **https://supabase.com** and click **Start your project**. Sign in with GitHub (easiest) or an email address.
2. Click **New project**:
   - **Name:** `date-night` (anything works).
   - **Database password:** click **Generate a password**. You won't need it for the app, but keep a copy somewhere safe.
   - **Region:** pick **London** (or the closest one to you).
   - Click **Create new project** and wait a minute or two while it sets up.
3. In the left sidebar, open the **SQL Editor** and click **New query**.
4. Open [`supabase.sql`](supabase.sql) (on GitHub, click **Raw** to see the plain text), copy **all** of it, paste it into the query box and click **Run**. You should see "Success. No rows returned". It's safe to run again if you're not sure it worked.
5. Find your project's address and key. Click **Connect** at the top of the project page, or go to **Project Settings → API Keys**. Copy:
   - the **Project URL**, which looks like `https://abcd1234.supabase.co`
   - the **publishable key** (starts with `sb_publishable_`). Older projects call it the **anon public** key (a long key starting with `eyJ`). Either works.

   Never use the **secret** or **service_role** key. The app doesn't need it.

## 2. Turn on sync on the laptop

1. Open Date Night Picker and click **Settings**, then **Sync between our devices**.
2. Under "First device?", paste the **Project URL** and the **key**, then click **Create our sync**.
3. The app shows a **pairing text** that starts with `datenight-sync:`. Click **Copy pairing text**.
4. Send it to both phones, for example in a WhatsApp chat between the two of you.

## 3. Join on each iPhone

1. Copy the pairing text from WhatsApp: press and hold the message, then tap **Copy**.
2. Open Date Night Picker from the home screen and tap **Settings**, then **Sync between our devices**.
3. Paste it into "Already set up on another device?" and tap **Join**.

That's it. Each device shows "Synced at 20:15" (or similar) near the top on the phone, or under the big pink button on the laptop. Anything already on a device before it joined is combined with the rest, not replaced.

## How it behaves

- **When it syncs:** when the app opens, every two minutes while it's open, a few seconds after any change, and on a phone whenever you switch back to the app. **Sync now** in the sync settings forces it straight away.
- **Offline:** the app works as normal and catches up next time it has a connection.
- **When two of you change things at once:** both changes are kept. If you both edit the same date, the most recent edit wins.
- **Deleting a date** removes it everywhere.
- **Photos:** each photo is uploaded once and downloaded by the other devices. Phone photos are shrunk before upload. On the laptop, very large photos (over about 2.6 MB) need Pillow to be shrunk (`sudo apt install python3-pil.imagetk`); otherwise they stay on the laptop only, and the sync status says so. The free plan's 500 MB holds roughly 2,000–3,000 photos.

## Good to know

- **The pairing text is like a password.** Anyone who has it can see and change your memories, so only send it to your own devices. The database itself can't be read without it: the setup script locks the tables and only allows the app's four sync functions.
- **Supabase pauses free projects that aren't used for a week.** Using the app keeps it awake. If it does pause, the app says it can't reach Supabase. Log in at supabase.com and click **Restore project**; nothing is lost.
- **Stopping sync:** **Stop syncing here** in the sync settings turns it off on that device. Everything already on the device stays. Delete the Supabase project to remove the online copy.
- **Backups still work** and are a good extra safety net. **Back up** in Memories saves everything, photos included, to one file.
