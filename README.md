# North East Museum Jobs

A small website that collects museum, gallery, archive and heritage vacancies in
Tyne & Wear, Northumberland, County Durham and Tees Valley. It reads the museums'
own careers pages and the regional job boards, because many of these jobs never
reach Indeed.

It runs on GitHub for free:

- A **GitHub Action** runs `scraper/scrape.py` twice a day (06:15 and 13:15 UK time).
  It checks every site in `scraper/sources.yaml` and saves the results to `docs/data/jobs.json`.
- **GitHub Pages** serves `docs/index.html`, which reads that file. Bookmark the page and it's always up to date.

## One-time setup (about 5 minutes)

1. **Create the repository.** On github.com click **New repository**, name it
   `ne-museum-jobs`, choose **Public** (Pages is free for public repos), and create it
   without a README.
2. **Upload the files.** On the empty repo page click **uploading an existing file**,
   then drag in everything from this folder, including the hidden `.github` folder.
   (On a Mac, press `Cmd+Shift+.` in Finder to show hidden folders.) Or, from Terminal:
   ```bash
   cd ~/Sites/ne-museum-jobs
   git init && git add . && git commit -m "First version"
   git branch -M main
   git remote add origin https://github.com/<your-username>/ne-museum-jobs.git
   git push -u origin main
   ```
3. **Let the Action save results.** Go to **Settings → Actions → General → Workflow
   permissions**, choose **Read and write permissions**, and click **Save**.
4. **Turn on the website.** Go to **Settings → Pages**. Under *Build and deployment*,
   choose **Deploy from a branch**, branch **main**, folder **/docs**, and click **Save**.
5. **Run the first check.** Go to the **Actions** tab, click **Update museum jobs**,
   then **Run workflow**. It takes 1–3 minutes.
6. Open `https://<your-username>.github.io/ne-museum-jobs/` and bookmark it.

## Using the site

- **New** flags jobs found since your last visit (on that browser).
- **Save** keeps a shortlist on that browser. It doesn't sync between devices.
- The **Where we look** table at the bottom shows every source. A red dot means the
  site couldn't be read on the last run, so open it directly.

## Adding or fixing a museum

Edit `scraper/sources.yaml` on GitHub (click the file, then the pencil icon).
Copy an existing `type: page` entry and change the `id`, `name`, `url` and `area`.
Commit, then run the Action from the Actions tab to check it.

Most museum sites work with `type: page`, which looks for headings and links that
read like job titles (Officer, Assistant, Curator and so on). If a site shows the
wrong things, add an `include:` pattern or move it to the `manual:` list.

## Running it on your own computer

```bash
pip install -r requirements.txt
python scraper/tests/test_scrape.py              # offline tests
python scraper/scrape.py --only bowes,beamish -v # check a couple of sources
python scraper/scrape.py                         # full run, writes docs/data/jobs.json
cd docs && python -m http.server 8000             # then open http://localhost:8000
```

## Notes

- The scraper waits between requests and identifies itself in its user agent. It
  visits each site about twice a day, the same as a person would.
- If a site fails, its last-known jobs stay on the list for up to 4 days, marked
  *Unconfirmed*.
- Jobs drop off once their closing date has passed.
