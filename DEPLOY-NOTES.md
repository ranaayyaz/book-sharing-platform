# Book Sharing Platform — FULL Online Version (Vercel)

Ye copy Vercel par bilkul waisi hi chalegi jaisi local par chalti hai:
register, login, books, borrow requests, covers aur PDF — sab kuch permanent save hoga.
Asal project folder ko haath nahi lagaya gaya; ye aik alag, online-ready copy hai.

## Tumhara sirf aik step: online database (Neon, free)

Vercel ki apni disk permanent nahi hoti, is liye database bahir rakhna parta hai.

1. neon.tech par jao → Google account se Sign Up karo (free plan, card nahi chahiye).
2. "Create Project" → naam kuch bhi (masalan book-sharing) → Create.
3. Dashboard par "Connection String" milegi — wo copy kar lena. Wo kuch aisi hogi:
   postgresql://user:password@ep-....aws.neon.tech/dbname?sslmode=require
4. Vercel me apne project ki Settings → Environment Variables me aik variable add karna:
   Name: DATABASE_URL    Value: (wohi connection string paste kar do)
5. Redeploy kar do. Pehli dafa site khulte hi tumhari asal 4 users, 7 books aur
   12 requests khud-ba-khud online database me aa jayengi (seed_data.json se).

Note: Connection string password jaisi hoti hai — kisi ko bhejna nahi, sirf Vercel ki
setting me dalna hai.

## Vercel par lagana

1. Is copy ki files aik GitHub repository ke ROOT me dal do.
2. Vercel.com → New Project → repo import → Deploy (koi setting nahi badalni;
   vercel.json aur requirements.txt tayyar hain).
3. Upar wala DATABASE_URL lazmi add karna, warna data permanent save nahi hoga.

## Is copy me kahan kia change hua

### app.py
- templates ka naam wala crash fix: code ab index.html mangta hai aur file ka naam
  bhi index.html kar diya gaya hai (pehle Index.html thi — Linux/Vercel par home
  page aur search crash hotay thay).
- Login crash fix: khaali email/password par ab sahi error message ata hai
  (pehle page crash ho jata tha — user = None add kiya).
- Register: console me password print karne wali line hata di.
- Module-level `app = create_app()` add kiya — Vercel ko ye chahiye hota hai.
- SECRET_KEY ab environment variable se bhi set ho sakta hai.
- Database: DATABASE_URL mile to online database (Neon Postgres) use hota hai;
  na mile to local SQLite pehle ki tarah. Vercel par bina DATABASE_URL ke /tmp
  wali temporary database chalegi (sirf safety ke liye rakhi hai).
- seed_database(): database khaali ho to seed_data.json se tumhara asal data
  (4 users, 7 books, 12 requests — passwords ke hashes same) load ho jata hai.
- Uploads ab Cloudinary par jate hain (upload_to_cloudinary function):
  book cover → image upload, PDF → raw upload. Cover/file ki jagah ab online
  URL save hota hai, is liye Vercel ki disk ki zaroorat hi nahi. Cloudinary
  fail ho to purana local tareeka fallback hai.
  (Cloud name aur preset abhi wahi hain jo Aura Store ke liye bane thay —
  chaaho to baad me is project ke liye alag preset bana lena.)
- static/uploads/books folder ab code khud banata hai (pehle missing tha,
  PDF upload crash hota tha) aur read-only disk par bhi crash nahi hota.

### templates/index.html (file ka naam Index.html se index.html)
- Cover wali line: agar cover online URL hai to seedha wahi dikhega, warna
  purani static file. Purani books ke covers pehle ki tarah chalenge.

### templates/admin_view_book.html
- Cover image ke liye wahi URL-wali logic.

### requirements.txt
- Sirf asal libraries: Flask, Flask-Login, Flask-SQLAlchemy, APScheduler,
  aur psycopg2-binary (online Postgres database ke liye driver).

### Nayi files
- vercel.json — Vercel ko batata hai ke ye Python (Flask) app hai.
- seed_data.json — tumhara asal data (users/books/requests) naye database
  ke liye.
- DEPLOY-NOTES.md — ye file.

## Test report (Lux ne chala kar verify kiya)
- Fresh database → seed se 4 users / 7 books / 12 requests load huay.
- Home page 200, login khaali fields par sahi message.
- Nayi book cover ke sath → cover Cloudinary URL ban gaya.
- Digital book PDF ke sath → PDF Cloudinary par gaya, borrower ko download
  par wahi link mila.
- Borrow → Accept → Borrowed → Return → Available: poora flow pass.
