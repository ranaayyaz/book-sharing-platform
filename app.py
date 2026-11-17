from fileinput import filename    # for handling and reading files
from functools import wraps   #  to make a decorator (admin, login  required)
from apscheduler.schedulers.background import BackgroundScheduler   # to schedule task in the background 
import re   # Email validation
from flask import Flask, Request, flash, render_template, url_for, request, redirect, abort
from flask_sqlalchemy import SQLAlchemy  # to map python classes in database table
from flask_login import LoginManager, UserMixin, login_user, current_user, login_required, logout_user 
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError  # handle duplicate user and emails
from werkzeug.security import generate_password_hash, check_password_hash  # to secure a password (hash and verify)
from urllib.parse import urlparse, urljoin   #validate redirect url
from datetime import timedelta, datetime  # to get current time and manage difference (7 days)
from flask import send_from_directory  # to download a pdf of digital books
import os   # to create uploads folder and check files
from werkzeug.utils import secure_filename  # To secure filename (security)

def admin_required(f):     #admin decorator to handle admin access
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role != 'admin':
               flash('You are not authorized to access this page!', 'danger')
               return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function

db = SQLAlchemy()   #  database object to handle all database operations 
login_manager = LoginManager()   # handle authentications


def auto_return_digital_books():   
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    # Find all accepted requests older than 7 days
    old_requests = Request.query.filter(
        Request.status == 'accepted',
        Request.created_at <= seven_days_ago
    ).all()
    for req in old_requests:
        book = Book.query.get(req.book_id)
        if book and book.type == 'digital' and book.status == 'borrowed':
            book.status = 'available'
            req.status = 'returned_auto'
            print(f"✅ Auto-returned: {book.title} (borrowed on {req.created_at.date()})")
    db.session.commit()

    #====================User Model=======================
    
class User(db.Model, UserMixin):     #  add essential authentications methods automatically
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='member')  
    is_blocked = db.Column(db.Boolean, default=False)  
    notification_count = db.Column(db.Integer, default=0) 

    def __repr__(self):
        return f"<User {self.username}>"
    

#==================Book Model==================

class Book(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50))
    type = db.Column(db.String(20))  # physical / digital
    description = db.Column(db.String(500))
    bg_class = db.Column(db.String(50))
    location = db.Column(db.String(200))
    file_path = db.Column(db.String(300))
    status = db.Column(db.String(20), default='available')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    cover_image = db.Column(db.String(300), default='default.jpg')
    owner = db.relationship('User', backref='books')
    def __repr__(self):
        return f"<Book {self.title}>"
    
    
    # ===============REQUEST MODEL ==================
    
class Request(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    book_id = db.Column(db.Integer, db.ForeignKey('book.id'), nullable=False)
    borrower_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    proposed_date = db.Column(db.String(50))
    proposed_time = db.Column(db.String(50))
    proposed_location = db.Column(db.String(200))
    message = db.Column(db.String(500))
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    book = db.relationship('Book', foreign_keys=[book_id])
    borrower = db.relationship('User', foreign_keys=[borrower_id])
    owner = db.relationship('User', foreign_keys=[owner_id])
    rejection_reason = db.Column(db.String(500)) 
    
    # NEW FIELDS FOR ALTERNATIVE SUGGESTION
    alternative_date = db.Column(db.String(50))
    alternative_time = db.Column(db.String(50)) 
    alternative_location = db.Column(db.String(200))
    is_read = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f"<Request {self.id} - {self.status}>"

def update_notification_count(user_id):         #  This function update user request and reject counts
        user = User.query.get(user_id)
        if user:
           my_books = Book.query.filter_by(user_id=user_id).all()
           book_ids = [book.id for book in my_books]
           owner_count = Request.query.filter(
                Request.book_id.in_(book_ids),
                Request.status == 'pending'
           ).count()
           borrower_count = Request.query.filter(
           Request.borrower_id == user_id,
           Request.status.in_(['accepted', 'rejected']),
           Request.is_read == False
           ).count()
           
           user.notification_count = owner_count + borrower_count
           db.session.commit()


def mark_notifications_read(user_id):         #   Notification Read Function 
        user = User.query.get(user_id)
        if user:
           user.notification_count = 0
           db.session.commit()





# ===== Cloudinary uploads: online storage for book covers & PDF files =====
CLOUDINARY_CLOUD_NAME = os.environ.get('CLOUDINARY_CLOUD_NAME', 'dlqzjthos')
CLOUDINARY_UPLOAD_PRESET = os.environ.get('CLOUDINARY_UPLOAD_PRESET', 'aura_unsigned')

def upload_to_cloudinary(file_storage, resource_type='image'):
    """Upload a file to Cloudinary using the unsigned preset.
    Returns the secure URL, or None if the upload fails."""
    import urllib.request
    import uuid
    import json as _json
    try:
        boundary = '----fyp' + uuid.uuid4().hex
        filename = secure_filename(file_storage.filename or 'upload')
        data = file_storage.read()
        file_storage.seek(0)
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            'Content-Type: application/octet-stream\r\n\r\n'
        ).encode() + data + (
            f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="upload_preset"\r\n\r\n'
            f'{CLOUDINARY_UPLOAD_PRESET}\r\n--{boundary}--\r\n'
        ).encode()
        req = urllib.request.Request(
            f'https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/{resource_type}/upload',
            data=body,
            headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = _json.loads(resp.read().decode())
        return result.get('secure_url')
    except Exception as e:
        print('Cloudinary upload failed:', e)
        return None


def seed_database():
    """One-time load of the original data (seed_data.json) when the database is empty.
    Keeps the same users, books and requests on a fresh online database."""
    try:
        if User.query.count() > 0:
            return
        import json
        seed_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'seed_data.json')
        if not os.path.exists(seed_path):
            return
        with open(seed_path, encoding='utf-8') as f:
            data = json.load(f)
        user_id_map = {}
        for row in data.get('users', []):
            u = User(username=row['username'], email=row['email'],
                     password_hash=row['password_hash'],
                     role=row.get('role') or 'member',
                     is_blocked=bool(row.get('is_blocked')),
                     notification_count=row.get('notification_count') or 0)
            db.session.add(u)
            db.session.flush()
            user_id_map[row['id']] = u.id
        book_id_map = {}
        for row in data.get('books', []):
            b = Book(title=row['title'], author=row['author'],
                     category=row.get('category'), type=row.get('type'),
                     description=row.get('description'), bg_class=row.get('bg_class'),
                     location=row.get('location'), file_path=row.get('file_path'),
                     status=row.get('status') or 'available',
                     user_id=user_id_map.get(row.get('user_id')),
                     cover_image=row.get('cover_image') or 'default.jpg')
            db.session.add(b)
            db.session.flush()
            book_id_map[row['id']] = b.id
        for row in data.get('requests', []):
            r = Request(book_id=book_id_map.get(row.get('book_id')),
                        borrower_id=user_id_map.get(row.get('borrower_id')),
                        owner_id=user_id_map.get(row.get('owner_id')),
                        proposed_date=row.get('proposed_date'),
                        proposed_time=row.get('proposed_time'),
                        proposed_location=row.get('proposed_location'),
                        message=row.get('message'),
                        status=row.get('status') or 'pending',
                        created_at=datetime.fromisoformat(row['created_at']) if row.get('created_at') else datetime.utcnow(),
                        rejection_reason=row.get('rejection_reason'),
                        alternative_date=row.get('alternative_date'),
                        alternative_time=row.get('alternative_time'),
                        alternative_location=row.get('alternative_location'),
                        is_read=bool(row.get('is_read')))
            db.session.add(r)
        db.session.commit()
        print('Seed data loaded: original users, books and requests restored.')
    except Exception as e:
        db.session.rollback()
        print('Seed skipped:', e)


def create_app():
    app = Flask(__name__)

    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_secret_key')
    #  database Path: DATABASE_URL if set (online db); on Vercel, /tmp seeded from the bundled database; local default otherwise
    _db_uri = os.environ.get('DATABASE_URL')
    if _db_uri:
        #  normalise to the psycopg2 driver: plain 'postgresql://' would make
        #  SQLAlchemy look for the psycopg v3 package, which is not installed
        _db_uri = _db_uri.replace('postgres://', 'postgresql://', 1)
        if _db_uri.startswith('postgresql://'):
            _db_uri = _db_uri.replace('postgresql://', 'postgresql+psycopg2://', 1)
    elif os.environ.get('VERCEL'):
        _tmp_db = '/tmp/database.db'
        if not os.path.exists(_tmp_db):
            _seed = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'database.db')
            if os.path.exists(_seed):
                import shutil
                shutil.copy(_seed, _tmp_db)
        _db_uri = 'sqlite:///' + _tmp_db
    else:
        _db_uri = 'sqlite:///database.db'
    app.config['SQLALCHEMY_DATABASE_URI'] = _db_uri
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False                  #  To improve performance
    app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=7)            #  Remember Me cookie valid
    
    UPLOAD_FOLDER = 'static/uploads/covers'
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
#  for image uploads
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024   # 16 MB limit for uploaded files
    try:
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        os.makedirs('static/uploads/books', exist_ok=True)
    except OSError:
        pass   # read-only filesystem (e.g. Vercel) - uploads fall back to defaults
    
    def allowed_file(filename):                #   check allowed extension
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS   
    
    db.init_app(app)                         #   connect database to flask app
    login_manager.init_app(app)              #   connect login system to flask app
    login_manager.login_view = 'login'       #   if logout redirect to login page
    login_manager.login_message_category = 'warning'   #   show the sign-in reminder as a proper warning box

    @app.before_request
    def before_request():
        if current_user.is_authenticated:
           auto_return_digital_books()
        
    with app.app_context():     #  create db
            db.create_all()
            seed_database()   #  one-time: restore original data on a fresh database


# ===============Authentication Routes=================

    @app.route("/login" , methods=["GET", "POST"])
    def login():
           errors = []
           if request.method == "POST":
                email=(request.form.get("email") or "").strip()
                password = request.form.get("password") or ""

                if not email:
                    errors.append("Email is required.")

                if not password:
                    errors.append("Password is required.")    
                
                user = None
                if not errors:
                     user = User.query.filter_by(email=email).first()

                if not user or not check_password_hash(user.password_hash, password):
                    errors.append("Invalid email or password.") 
                elif user.is_blocked: 
                    errors.append("Your account has been blocked. Contact admin.")

                else:  
                    remember_flag = request.form.get("remember") == "1"
                    login_user(user, remember=remember_flag)

                    return redirect(url_for("dashboard"))    
                 
           return render_template("login.html", errors=errors)
    

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    @app.route("/logout")
    def logout():
        logout_user()
        return redirect(url_for("index"))

# =======================Register Route==========================

    @app.route("/register", methods=["GET", "POST"])
    def register():
            errors = []
            if request.method == "POST":
                username = (request.form.get("username") or "").strip()
                email = (request.form.get("email") or "").strip()
                password = request.form.get("password") or ""
                confirm_password = request.form.get("confirm_password") or ""
                
                if not (3 <= len(username) <= 80):
                    errors.append("Username must be between 3 and 80 characters.")
                     
                if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
                    errors.append("Invalid email format.")

                if len(password) < 6:
                    errors.append("Password must be at least 6 characters long.")
            
            
                if password != confirm_password:
                    errors.append("Passwords do not match.")

                if not errors:
                     try:
                          pw_hash = generate_password_hash(password)
                          user = User(username=username, email=email, password_hash=pw_hash)
                          db.session.add(user)
                          db.session.commit()
                          flash("Registration successful. Please log in.", "success")
                          return redirect(url_for("login"))
                     

                     except IntegrityError:
                          db.session.rollback()
                          errors.append("Username or email already exists.")

            return render_template("register.html", errors=errors)

# ================================Book Detail Route==========================

    @app.route('/book/<int:book_id>')
    def book_detail(book_id):
        book = Book.query.get_or_404(book_id)
    
        user_requests = {}
        has_borrowed = False
        is_owner = False
    
        if current_user.is_authenticated:
           user_req_list = Request.query.filter_by(borrower_id=current_user.id).all()
           user_requests = {req.book_id: req for req in user_req_list}
        
        # Check if current user has borrowed this book
        
           accepted_req = Request.query.filter_by(borrower_id=current_user.id, book_id=book_id, status='accepted').first()
           has_borrowed = accepted_req is not None
        
           is_owner = (book.user_id == current_user.id)
    
        return render_template('book_detail.html', 
                         book=book, 
                         user_requests=user_requests,
                         has_borrowed=has_borrowed,
                         is_owner=is_owner)
        
#=============================  Home Route=======================       
    
    @app.route('/')
    def home():
        books = Book.query.all()
    
        user_requests = {}
        borrowed_books = set()
        owned_books = set()
    
        if current_user.is_authenticated:
            
        # User Owned Books
        
            owned_books = {book.id for book in Book.query.filter_by(user_id=current_user.id).all()}
        
        # User sent requests (pending, accepted, rejected)
        
            user_req_list = Request.query.filter_by(borrower_id=current_user.id).all()
            user_requests = {req.book_id: req for req in user_req_list}
           
        # User borrowed books (accepted requests)
        
            accepted_req = Request.query.filter_by(borrower_id=current_user.id, status='accepted').all()
            borrowed_books = {req.book_id for req in accepted_req}
    
        return render_template('index.html', 
                         books=books, 
                         user_requests=user_requests,
                         borrowed_books=borrowed_books,
                         owned_books=owned_books)


    #================Return Route========================
    
    @app.route('/return_book/<int:book_id>')
    @login_required
    def return_book(book_id):
        book = Book.query.get_or_404(book_id)
    
    # Check book status for current user
        request = Request.query.filter_by(book_id=book_id, borrower_id=current_user.id, status='accepted').first()
        if not request:
           flash('You have not borrowed this book!', 'danger')
           return redirect(url_for('home'))
        book.status = 'available'
        request.status = 'returned'
        db.session.commit()
    
        flash(f'✅ "{book.title}" has been returned successfully!', 'success')
        return redirect(url_for('home'))

#========================Borrow Route========================

    @app.route('/borrow/<int:book_id>/<string:book_slug>')
    @login_required
    def borrow_book(book_id, book_slug):
        book = Book.query.get_or_404(book_id)
        return render_template('borrow.html', book=book)

#========================Request Book Route========================

    @app.route('/request_book/<int:book_id>', methods=['POST'])
    @login_required
    def request_book(book_id):
        book = Book.query.get_or_404(book_id)
    
    # =====Check book status=====
    
        if book.status != 'available':
           flash('This book is no longer available!', 'danger')
           return redirect(url_for('home'))
    
    # =====Owner not borrow own books=====
    
        if book.user_id == current_user.id:
           flash('You cannot request your own book!', 'danger')
           return redirect(url_for('home'))
    
    # ===========Form Data==========
    
        proposed_date = request.form.get('proposed_date')
        proposed_time = request.form.get('proposed_time')
        proposed_location = request.form.get('proposed_location')
        message = request.form.get('message', '')
    
    # =========Request save ===========
        new_request = Request(
            book_id=book.id,
            borrower_id=current_user.id,
            owner_id=book.user_id,
            proposed_date=proposed_date,
            proposed_time=proposed_time,
            proposed_location=proposed_location,
            message=message,
            status='pending'
        )
    
        db.session.add(new_request)
        db.session.commit()
        update_notification_count(book.user_id) 
        flash(f'✅ Request for "{book.title}" sent successfully!', 'success')
        return redirect(url_for('dashboard'))


#=========================Requests Sent Route========================

    @app.route('/requests_sent')
    @login_required
    def requests_sent():
    # =====Borrower Requests check=====
        requests = Request.query.filter_by(borrower_id=current_user.id).order_by(Request.created_at.desc()).all()
        return render_template('requests_sent.html', requests=requests)

#=========================Requests Received Route========================

    @app.route('/requests_received')
    @login_required
    def requests_received():
    # =====Owner Requests check=====
       my_books = Book.query.filter_by(user_id=current_user.id).all()
       book_ids = [book.id for book in my_books]
       requests = Request.query.filter(Request.book_id.in_(book_ids)).order_by(Request.created_at.desc()).all()
       return render_template('requests_received.html', requests=requests)

#=========================Accept Request Route========================


    @app.route('/accept_request/<int:request_id>')
    @login_required
    def accept_request(request_id):
        req = Request.query.get_or_404(request_id)
    
    # =====Check current user request=====
    
        if req.owner_id != current_user.id:
           flash('You are not authorized!', 'danger')
           return redirect(url_for('dashboard'))
        book = Book.query.get(req.book_id)    
        req.status = 'accepted'
        req.is_read = False
        book.status = 'borrowed'
        book = Book.query.get(req.book_id)
        book.status = 'borrowed'
        db.session.commit()
        update_notification_count(req.borrower_id)  
        flash(f'Request for "{book.title}" accepted!', 'success')
        return redirect(url_for('requests_received'))

#=========================Reject Request Route========================

    @app.route('/reject_request/<int:request_id>', methods=['POST'])
    @login_required
    def reject_request(request_id):
        req = Request.query.get_or_404(request_id)
    
        if req.owner_id != current_user.id:
           flash('You are not authorized!', 'danger')
           return redirect(url_for('dashboard'))
    
        rejection_reason = request.form.get('rejection_reason', '')
    
        req.status = 'rejected'
        req.is_read = False
        req.rejection_reason = rejection_reason
        db.session.commit()
        update_notification_count(req.borrower_id)
        flash(f'Request for "{req.book.title}" rejected! Reason: {rejection_reason}', 'danger')
        return redirect(url_for('requests_received'))
    
#=========================Search Route========================

    @app.route('/search')
    def search():
        query = request.args.get('q', '')
    
        if query:
        # Search by title, author, or category
           books = Book.query.filter(
              (Book.title.ilike(f'%{query}%')) |
              (Book.author.ilike(f'%{query}%')) |
              (Book.category.ilike(f'%{query}%'))
        ).filter_by(status='available').all()
        else:
            books = Book.query.filter_by(status='available').all()
    
        return render_template('index.html', books=books, search_query=query)

#=========================Add Book Route========================

    @app.route('/add_book', methods=['GET', 'POST'])
    @login_required
    def add_book():
       if request.method == 'POST':
          title = request.form.get('title')
          author = request.form.get('author')
          category = request.form.get('category')
          book_type = request.form.get('book_type')
          description = request.form.get('description')
          location = request.form.get('location') if book_type == 'physical' else None
        
        #======FILE UPLOAD LOGIC========
          file_path = None
          pdf_filename = None
          download_link = request.form.get('download_link')
          if 'file' in request.files:
             file = request.files['file']
             if file and file.filename:
                filename = secure_filename(file.filename)
                pdf_url = upload_to_cloudinary(file, 'raw')
                if pdf_url:
                    pdf_filename = pdf_url   # online file URL (opens via the download route)
                else:
                    try:
                        file.save(os.path.join('static/uploads/books', filename))
                        pdf_filename = filename
                    except OSError:
                        pdf_filename = None   # storage unavailable
        
          if pdf_filename and download_link:
             file_path = f"{pdf_filename}|{download_link}"
          elif pdf_filename:
             file_path = pdf_filename
          elif download_link:
             file_path = download_link
        
        #====Default Cover Page for books============
        
          cover_filename = 'default.jpg'
          if 'cover_image' in request.files:
            file = request.files['cover_image']
            if file and file.filename:
                filename = secure_filename(file.filename)
                import time
                cover_filename = f"{int(time.time())}_{filename}"
                cover_url = upload_to_cloudinary(file, 'image')
                if cover_url:
                    cover_filename = cover_url   # online image URL
                else:
                    try:
                        file.save(os.path.join(app.config['UPLOAD_FOLDER'], cover_filename))
                    except OSError:
                        cover_filename = 'default.jpg'   # storage unavailable fallback
        
          new_book = Book(
            title=title,
            author=author,
            category=category,
            type=book_type,
            description=description,
            location=location,
            cover_image=cover_filename,
            file_path=file_path,
            bg_class='bg-dynamic',
            user_id=current_user.id,
            status='available'
          )
        
          db.session.add(new_book)
          db.session.commit()
          flash(f'📚 "{new_book.title}" has been added successfully!', 'success')
          return redirect(url_for('dashboard'))
    
       return render_template('add_book.html')

#=========================My Books Route========================

    @app.route('/my_books')
    @login_required
    def my_books():
        user_books = Book.query.filter_by(user_id=current_user.id).all() 
        return render_template('my_books.html', books=user_books)
    
#=========================Borrowed Books Route========================

    @app.route('/borrowed_books')
    @login_required
    def borrowed_books():
    # Borrowed Books accepted status
       borrowed_books = Request.query.filter_by(
          borrower_id=current_user.id, 
          status='accepted'
        ).all()
    
       return render_template('borrowed_books.html', borrowed_books=borrowed_books)

#=========================User Dashboard Route========================

    @app.route('/dashboard')
    @login_required
    def dashboard():
    # For Admin Dashboard
        if current_user.role == 'admin':
           return redirect(url_for('admin_dashboard'))
    
    # For Member Dashboard
    
        borrowed_books = Request.query.filter_by(borrower_id=current_user.id, status='accepted').all()
        return render_template('dashboard.html', borrowed_books=borrowed_books)

#=========================Profile Route========================

    @app.route('/profile', methods=['GET', 'POST'])
    @login_required
    def profile():
        errors = []
    
    # Counts for profile stats
    
        books_shared = Book.query.filter_by(user_id=current_user.id).count()
        books_borrowed = Request.query.filter_by(borrower_id=current_user.id, status='accepted').count()
        total_requests = Request.query.filter_by(borrower_id=current_user.id, status='pending').count()
    
        if request.method == "POST":
           current_pw = request.form.get("current_password") or ""
           new_pw = request.form.get("new_password") or ""
           confirm_pw = request.form.get("confirm_password") or ""

           if not check_password_hash(current_user.password_hash, current_pw):
              flash("Current password is incorrect.", "danger")
              errors.append("Current password is incorrect.")

           if len(new_pw) < 6:
               errors.append("New password must be at least 6 characters long.")
           if new_pw != confirm_pw:
              flash("New Password and confirmation do not match.", "danger")
              errors.append("New Password and confirmation do not match.")
           if not errors:
               current_user.password_hash = generate_password_hash(new_pw)
               db.session.commit()
               flash("Password updated successfully.", "success")
               return redirect(url_for("profile"))

        return render_template('profile.html', 
                         errors=errors,
                         books_shared=books_shared,
                         books_borrowed=books_borrowed,
                         total_requests=total_requests)

#=========================Index Route========================

    @app.route("/")  
    def index(): 
          return render_template("index.html")


# ========== DELETE BOOK ROUTE ===================

    @app.route('/delete_book/<int:book_id>')
    @login_required
    def delete_book(book_id):
    # Find Books
        book = Book.query.get(book_id)
    
    # If not available book, flash message and return 404
    
        if not book:
           flash('Book not found!', 'danger')

           return "Book not found", 404
        book_title = book.title 
        
    #=====check current user is owner or not========
    
        if book.user_id != current_user.id:
           flash('You are not authorized to delete this book!', 'danger')
           return "You are not authorized to delete this book", 403
        book_title = book.title
        requests = Request.query.filter_by(book_id=book.id).all()
        for req in requests:
           db.session.delete(req)
    # ===Delete Book===
        db.session.delete(book)
        db.session.commit()
        success_msg = f'📚 "{book_title}" has been deleted successfully!'
        flash(success_msg, 'success')
        return redirect(url_for('my_books'))

#=========================Edit Book Route========================

    @app.route('/edit_book/<int:book_id>', methods=['GET', 'POST'])
    @login_required
    def edit_book(book_id):
        book = Book.query.get(book_id)
        if not book:
           flash('Book not found!', 'danger')
           return redirect(url_for('my_books'))
    
        if book.user_id != current_user.id:
           flash('You are not authorized to edit this book!', 'danger')
           return redirect(url_for('my_books'))
    
        if request.method == 'POST':
           book.title = request.form.get('title')
           book.author = request.form.get('author')
           book.category = request.form.get('category')
           book.type = request.form.get('book_type')
           book.location = request.form.get('location', '')
           book.description = request.form.get('description', '')
           
           if 'cover_image' in request.files:
            file = request.files['cover_image']
            if file and file.filename:
                filename = secure_filename(file.filename)
                import time
                cover_filename = f"{int(time.time())}_{filename}"
                cover_url = upload_to_cloudinary(file, 'image')
                if cover_url:
                    cover_filename = cover_url   # online image URL
                else:
                    try:
                        file.save(os.path.join(app.config['UPLOAD_FOLDER'], cover_filename))
                    except OSError:
                        cover_filename = 'default.jpg'   # storage unavailable fallback
                book.cover_image = cover_filename
        
           if book.type == 'digital':
              book.location = ''
           db.session.commit()
           flash(f'📚 "{book.title}" has been updated successfully!', 'success')
           return redirect(url_for('my_books'))
    
        return render_template('edit_book.html', book=book)

#=========================Admin Dashboard Route========================

    @app.route('/admin')
    @login_required
    @admin_required
    def admin_dashboard():
    # ====Fetch All users=====
        users = User.query.all()
    #=======Fetch All books========
        books = Book.query.all()
        return render_template('admin.html', users=users, books=books)

#=========================Admin Delete Book Route========================

    @app.route('/admin/delete_book/<int:book_id>')
    @login_required
    @admin_required
    def admin_delete_book(book_id):
        book = Book.query.get(book_id)
        if book:
           requests = Request.query.filter_by(book_id=book.id).all()
           for req in requests:
               db.session.delete(req)
           db.session.delete(book)
           db.session.commit()
        flash(f'Book "{book.title}" has been deleted by admin!', 'success')
        return redirect(url_for('admin_dashboard'))

#=========================Admin Delete User Route========================

    @app.route('/admin/delete_user/<int:user_id>')
    @login_required
    @admin_required
    def admin_delete_user(user_id):
        user = User.query.get(user_id)
        if user and user.role != 'admin':
           db.session.delete(user)
           db.session.commit()
        flash(f'User "{user.username}" has been deleted!', 'success')
        return redirect(url_for('admin_dashboard'))

#=========================Admin Toggle Block User Route========================

    @app.route('/admin/toggle_block/<int:user_id>')
    @login_required
    @admin_required
    def admin_toggle_block(user_id):
        user = User.query.get(user_id)
        if user and user.role != 'admin':
           user.is_blocked = not getattr(user, 'is_blocked', False)
           db.session.commit()
           status = "blocked" if user.is_blocked else "unblocked"
           flash(f'User "{user.username}" has been {status}!', 'success')
           return redirect(request.referrer or url_for('admin_users'))

#=========================Admin View User Details Route========================

    @app.route('/admin/view_user/<int:user_id>')
    @login_required
    @admin_required
    def admin_view_user(user_id):
        user = User.query.get_or_404(user_id)
        books = Book.query.filter_by(user_id=user_id).all()
        return render_template('admin_view_user.html', user=user, books=books)
    
#========================Suggest Alternative Route========================
    
    @app.route('/suggest_alternative/<int:request_id>', methods=['GET', 'POST'])
    @login_required
    def suggest_alternative(request_id):
        req = Request.query.get_or_404(request_id)
    
    # Only Owner can suggest alternative
    
        if req.owner_id != current_user.id:
           flash('You are not authorized!', 'danger')
           return redirect(url_for('dashboard'))
    
        if request.method == 'POST':
        # Save alternative suggestions
           req.alternative_date = request.form.get('alternative_date')
           req.alternative_time = request.form.get('alternative_time')
           req.alternative_location = request.form.get('alternative_location')
           req.status = 'alternative_suggested'
           db.session.commit()
           flash(f'✅ Alternative suggested for "{req.book.title}"!', 'success')
           return redirect(url_for('requests_received'))
    
        return render_template('suggest_alternative.html', request=req)
    
    
#========================Accept Alternative Route========================
    
    @app.route('/accept_alternative/<int:request_id>')
    @login_required
    def accept_alternative(request_id):
        req = Request.query.get_or_404(request_id)
    
    # Check request belongs to current user (borrower)
    
        if req.borrower_id != current_user.id:
           flash('You are not authorized!', 'danger')
           return redirect(url_for('dashboard'))
    
    # copy alternative fields to proposed fields if they exist
        if req.alternative_date:
           req.proposed_date = req.alternative_date
        if req.alternative_time:
           req.proposed_time = req.alternative_time
        if req.alternative_location:
           req.proposed_location = req.alternative_location
    
    # clear alternative fields after accepting
    
        req.alternative_date = None
        req.alternative_time = None
        req.alternative_location = None
    
    # Status return pending
        req.status = 'pending'
        db.session.commit()
    
        flash('✅ You accepted the alternative suggestion! Request sent to owner again.', 'success')
        return redirect(url_for('requests_sent'))
    
 #========================Reject Alternative Route========================   
    
    @app.route('/reject_alternative/<int:request_id>')
    @login_required
    def reject_alternative(request_id):
        req = Request.query.get_or_404(request_id)
    
    # Check request belongs to current user (borrower)
    
        if req.borrower_id != current_user.id:
           flash('You are not authorized!', 'danger')
           return redirect(url_for('dashboard'))
    
    # clear alternative fields and keep original proposed fields intact
    
        req.alternative_date = None
        req.alternative_time = None
        req.alternative_location = None
        req.status = 'pending'
        db.session.commit()
    
        flash('ℹ️ You rejected the alternative suggestion. Original request is still pending.', 'info')
        return redirect(url_for('requests_sent'))

 #========================Download Book Route========================   

    @app.route('/download/<int:book_id>')
    @login_required
    def download_book(book_id):
        book = Book.query.get_or_404(book_id)

    # Check if user has borrowed this book
        borrow_record = Request.query.filter_by(
            book_id=book_id, 
            borrower_id=current_user.id, 
            status='accepted'
        ).first()

        if not borrow_record:
           flash('You have not borrowed this book!', 'danger')
           return redirect(url_for('home'))

        if book.type != 'digital':
           flash('This is not a digital book!', 'danger')
           return redirect(url_for('home'))

        if not book.file_path:
           flash('No download link available!', 'danger')
           return redirect(url_for('borrowed_books'))

    # Handle cases where file_path might contain both filename and external link separated by '|'
    
        if '|' in book.file_path:
           file_to_download = book.file_path.split('|')[0]
        else:
          file_to_download = book.file_path

    # Check if it's a URL or a file
    
        if file_to_download.startswith('http'):
           return redirect(file_to_download)
        import os
        file_full_path = os.path.join('static/uploads/books', file_to_download)
        if not os.path.exists(file_full_path):
           flash('File not found on server!', 'danger')
           return redirect(url_for('borrowed_books'))

        return send_from_directory('static/uploads/books', file_to_download, as_attachment=True)

#========================Admin View Book Details Route========================

    @app.route('/admin/view_book/<int:book_id>')
    @login_required
    @admin_required
    def admin_view_book(book_id):
       book = Book.query.get_or_404(book_id)
       return render_template('admin_view_book.html', book=book)

#========================Admin View Users Route========================

    @app.route('/admin/users')
    @login_required
    @admin_required
    def admin_users():
       users = User.query.all()
       return render_template('admin_users.html', users=users)

#========================Admin View Books Route========================

    @app.route('/admin/books')
    @login_required
    @admin_required
    def admin_books():
       books = Book.query.all()
       return render_template('admin_books.html', books=books)

#========================Admin View Blocked Users Route========================

    @app.route('/admin/blocked-users')
    @login_required
    @admin_required
    def admin_blocked_users():
        users = User.query.filter_by(is_blocked=True).all()
        return render_template('admin_users.html', users=users)

#========================Notifications Route========================

    @app.route('/notifications')
    @login_required
    def notifications():
        
        Request.query.filter_by(borrower_id=current_user.id).update({'is_read': True})
        db.session.commit()
        mark_notifications_read(current_user.id)    # helper function to zero the bell count
    
        my_books = Book.query.filter_by(user_id=current_user.id).all()
        book_ids = [book.id for book in my_books]
    
        received_requests = Request.query.filter(
           Request.book_id.in_(book_ids),
           Request.status == 'pending'
        ).order_by(Request.created_at.desc()).all()
    
        sent_requests = Request.query.filter_by(
           borrower_id=current_user.id
        ).order_by(Request.created_at.desc()).all()
    
        return render_template('notifications.html', 
                         received_requests=received_requests,
                         sent_requests=sent_requests)


    return app

app = create_app()   # module-level app for Vercel / WSGI servers

if __name__ == "__main__":
    app.run(debug=True)
