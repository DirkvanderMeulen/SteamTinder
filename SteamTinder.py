import tkinter as tk
from tkinter import messagebox, filedialog, simpledialog
import csv
import json
import os
import atexit
import sqlite3
import getpass
from datetime import datetime
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import sys

# Configuration constants
CONFIG_FILE = "steam_tinder_config.json"
DEFAULT_CONFIG = {
    "database_path": "steam_tinder.db",
    "browser": "Chrome",
    "always_on_top": False
}

class DatabaseManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self.initialize_database()
        self.migrate_database()  # Run migrations to add any missing columns

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def initialize_database(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Create games table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS games (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    developers TEXT,
                    release_date TEXT,
                    steam_page_url TEXT NOT NULL,
                    batch_name TEXT NOT NULL,
                    UNIQUE(steam_page_url, batch_name)
                )
            ''')
            
            # Create votes table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS votes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id INTEGER NOT NULL,
                    user_name TEXT NOT NULL,
                    vote BOOLEAN NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    exported BOOLEAN DEFAULT 0,
                    FOREIGN KEY (game_id) REFERENCES games(id),
                    UNIQUE(game_id, user_name)
                )
            ''')
            
            # Create progress table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS progress (
                    user_name TEXT NOT NULL,
                    batch_name TEXT NOT NULL,
                    current_index INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (user_name, batch_name)
                )
            ''')
            
            conn.commit()

    def migrate_database(self):
        """Perform any needed database migrations for schema updates"""
        print("Running database migrations...")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Check if exported column exists in votes table
            cursor.execute("PRAGMA table_info(votes)")
            columns = [row[1] for row in cursor.fetchall()]
            print(f"Current columns in votes table: {columns}")
            
            # Add exported column if it doesn't exist
            if 'exported' not in columns:
                try:
                    # For SQLite 3.20.0 and later:
                    cursor.execute("""
                        ALTER TABLE votes ADD COLUMN exported BOOLEAN DEFAULT 0
                    """)
                    print("Added 'exported' column to votes table")
                    
                    # Initialize all existing votes as not exported
                    cursor.execute("UPDATE votes SET exported = 0")
                    print(f"Updated {cursor.rowcount} existing votes to exported=0")
                    
                    conn.commit()
                    
                    # Verify the column was added
                    cursor.execute("PRAGMA table_info(votes)")
                    updated_columns = [row[1] for row in cursor.fetchall()]
                    print(f"Updated columns in votes table: {updated_columns}")
                    
                except sqlite3.OperationalError as e:
                    print(f"Migration error: {e}")
                    
                    # Alternative approach for older SQLite versions
                    try:
                        print("Trying alternative migration approach...")
                        
                        # Create new table with the desired schema
                        cursor.execute('''
                            CREATE TABLE votes_new (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                game_id INTEGER NOT NULL,
                                user_name TEXT NOT NULL,
                                vote BOOLEAN NOT NULL,
                                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                                exported BOOLEAN DEFAULT 0,
                                FOREIGN KEY (game_id) REFERENCES games(id),
                                UNIQUE(game_id, user_name)
                            )
                        ''')
                        
                        # Copy data from old table to new table
                        cursor.execute('''
                            INSERT INTO votes_new (id, game_id, user_name, vote, timestamp)
                            SELECT id, game_id, user_name, vote, timestamp FROM votes
                        ''')
                        
                        # Drop old table and rename new table
                        cursor.execute('DROP TABLE votes')
                        cursor.execute('ALTER TABLE votes_new RENAME TO votes')
                        
                        print("Successfully migrated votes table using alternative approach")
                        conn.commit()
                    except sqlite3.Error as e2:
                        print(f"Alternative migration failed: {e2}")
                        conn.rollback()

class SteamGameVoter:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Steam Tinder")
        self.root.geometry("500x400")
        self.entries = []
        self.current_index = 0
        self.fieldnames = []
        self.driver = None
        self.input_filename = ""
        self.process_completed = False
        self.user_name = getpass.getuser()  # Get current system username
        
        # Initialize UI elements that might be accessed before creation
        self.status_label = None
        self.db_label = None
        
        # Load configuration
        self.config = self.load_config()
        
        # Setup variables with values from config
        self.browser_var = tk.StringVar(value=self.config.get("browser", "Chrome"))
        self.always_on_top_var = tk.BooleanVar(value=self.config.get("always_on_top", False))
        
        # Setup database
        self.db_path = self.config.get("database_path", os.path.join(os.path.dirname(os.path.abspath(__file__)), "steam_tinder.db"))
        self.db = None
        
        # Create initial UI for database/file selection
        self.create_initial_ui()
        
        # Connect to database if path exists (after UI is created)
        if os.path.exists(self.db_path):
            self.ensure_db_connection()

    def load_config(self):
        """Load configuration from file or create default if not exists"""
        config_locations = [
            # 1. Look in the same directory as the executable
            os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), CONFIG_FILE),
            # 2. Look in the current working directory
            CONFIG_FILE
        ]
        
        # Try each location
        for config_path in config_locations:
            if os.path.exists(config_path):
                try:
                    with open(config_path, 'r') as f:
                        config = json.load(f)
                    print(f"Loaded configuration from {config_path}")
                    return config
                except Exception as e:
                    print(f"Error loading config from {config_path}: {e}")
        
        # If no config found, use defaults
        print(f"Config file not found in any location, using defaults")
        return DEFAULT_CONFIG.copy()
            
    def save_config(self):
        """Save current configuration to file"""
        try:
            # Update config with current settings
            if hasattr(self, 'db_path'):
                self.config["database_path"] = self.db_path
                
            if hasattr(self, 'browser_var'):
                self.config["browser"] = self.browser_var.get()
                
            if hasattr(self, 'always_on_top_var'):
                self.config["always_on_top"] = self.always_on_top_var.get()
            
            # Save to the executable directory first if possible, otherwise to current directory
            config_path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), CONFIG_FILE)
            with open(config_path, 'w') as f:
                json.dump(self.config, f, indent=4)
            print(f"Configuration saved to {config_path}")
        except Exception as e:
            print(f"Error saving config: {e}")
            # Try saving to current directory as fallback
            try:
                with open(CONFIG_FILE, 'w') as f:
                    json.dump(self.config, f, indent=4)
                print(f"Configuration saved to {CONFIG_FILE} (fallback)")
            except Exception as e2:
                print(f"Error saving config to fallback location: {e2}")

    def __del__(self):
        """Clean up resources when object is destroyed"""
        try:
            if hasattr(self, 'driver') and self.driver:
                self.driver.quit()
                
            if hasattr(self, 'db') and self.db:
                self.save_progress()
                
            # Save config when exiting
            if hasattr(self, 'config'):
                self.save_config()
        except Exception as e:
            print(f"Error during cleanup: {e}")

    def create_initial_ui(self):
        self.root.configure(bg='#f0f0f0')
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        main_frame = tk.Frame(self.root, bg='#f0f0f0')
        main_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        
        # Application title
        title_label = tk.Label(main_frame, text="Steam Tinder", font=('Arial', 18, 'bold'), bg='#f0f0f0')
        title_label.grid(row=0, column=0, pady=(10, 20))
        
        # Database section
        db_frame = tk.LabelFrame(main_frame, text="Database", padx=10, pady=10, bg='#f0f0f0')
        db_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        
        # Show current database
        db_path_display = os.path.basename(self.db_path) if self.db_path else "No database selected"
        self.db_label = tk.Label(db_frame, text=f"Current Database: {db_path_display}", 
                              bg='#f0f0f0', font=('Arial', 10))
        self.db_label.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 5))
        
        open_db_button = tk.Button(db_frame, text="Open Database", command=self.select_database,
                                  width=20, bg='#4CAF50', fg='white', font=('Arial', 10))
        open_db_button.grid(row=1, column=0, padx=5, pady=5)
        
        # Add a button to create a new database
        new_db_button = tk.Button(db_frame, text="Create New Database", command=self.create_new_database,
                                width=20, bg='#4CAF50', fg='white', font=('Arial', 10))
        new_db_button.grid(row=1, column=1, padx=5, pady=5)
        
        # CSV operations section
        csv_frame = tk.LabelFrame(main_frame, text="CSV Operations", padx=10, pady=10, bg='#f0f0f0')
        csv_frame.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        
        import_button = tk.Button(csv_frame, text="Import CSV & Start Swiping", command=self.select_file,
                                 width=25, bg='#2196F3', fg='white', font=('Arial', 10))
        import_button.grid(row=0, column=0, padx=5, pady=5)
        
        import_dataset_button = tk.Button(csv_frame, text="Import CSV to Database Only", 
                                       command=self.import_additional_dataset,
                                       width=25, bg='#2196F3', fg='white', font=('Arial', 10))
        import_dataset_button.grid(row=0, column=1, padx=5, pady=5)
        
        export_button = tk.Button(csv_frame, text="Export New Yes Votes", command=self.export_new_yes_votes,
                                 width=25, bg='#FF9800', fg='white', font=('Arial', 10))
        export_button.grid(row=1, column=0, padx=5, pady=5)
        
        select_batch_button = tk.Button(csv_frame, text="Select Batch to Swipe", command=self.select_batch_from_db,
                                     width=25, bg='#9C27B0', fg='white', font=('Arial', 10))
        select_batch_button.grid(row=1, column=1, padx=5, pady=5)
        
        # Add a button for unvoted games
        unvoted_button = tk.Button(csv_frame, text="Swipe Unvoted Games", command=self.swipe_unvoted_games,
                                 width=25, bg='#E91E63', fg='white', font=('Arial', 10))
        unvoted_button.grid(row=2, column=0, padx=5, pady=5)
        
        # Add a button to wipe votes after export
        wipe_button = tk.Button(csv_frame, text="Wipe Database Completely", command=self.wipe_votes_with_confirmation,
                              width=25, bg='#F44336', fg='white', font=('Arial', 10))
        wipe_button.grid(row=2, column=1, padx=5, pady=5)
        
        # Exit button
        exit_button = tk.Button(main_frame, text="Exit", command=self.close_application,
                               width=10, bg='#f44336', fg='white', font=('Arial', 10))
        exit_button.grid(row=3, column=0, pady=(10, 0))
        
        # Status label
        self.status_label = tk.Label(main_frame, text="Ready", bg='#f0f0f0', font=('Arial', 10))
        self.status_label.grid(row=4, column=0, pady=(10, 0))
        
        # Always on top
        always_on_top_check = tk.Checkbutton(main_frame, text="Keep this window in foreground", 
                                             variable=self.always_on_top_var,
                                             command=self.toggle_always_on_top, bg='#f0f0f0')
        always_on_top_check.grid(row=5, column=0, sticky="w", pady=(10, 0))

    def select_database(self):
        selected_db = filedialog.askopenfilename(
            title="Select SQLite Database",
            filetypes=[("SQLite Database", "*.db"), ("All Files", "*.*")]
        )
        
        if selected_db:
            self.db_path = selected_db
            self.db = DatabaseManager(self.db_path)
            self.update_db_label()
            self.status_label.config(text=f"Connected to database: {os.path.basename(self.db_path)}")
            messagebox.showinfo("Database Connected", f"Connected to: {os.path.basename(self.db_path)}")
            # Save the new database path to config
            self.save_config()
            
    def create_new_database(self):
        """Create a new database file"""
        new_db_path = filedialog.asksaveasfilename(
            title="Create New Database",
            defaultextension=".db",
            filetypes=[("SQLite Database", "*.db"), ("All Files", "*.*")]
        )
        
        if new_db_path:
            self.db_path = new_db_path
            self.db = DatabaseManager(self.db_path)
            self.update_db_label()
            self.status_label.config(text=f"Created and connected to: {os.path.basename(self.db_path)}")
            messagebox.showinfo("Database Created", f"Created new database: {os.path.basename(self.db_path)}")
            # Save the new database path to config
            self.save_config()
            
    def update_db_label(self):
        """Update the database label in the UI"""
        if hasattr(self, 'db_label') and self.db_label:
            db_path_display = os.path.basename(self.db_path) if self.db_path else "No database selected"
            self.db_label.config(text=f"Current Database: {db_path_display}")

    def ensure_db_connection(self):
        """Ensure we have a valid database connection"""
        try:
            if not hasattr(self, 'db') or self.db is None:
                self.db = DatabaseManager(self.db_path)
                self.update_db_label()
                if hasattr(self, 'status_label') and self.status_label:
                    self.status_label.config(text=f"Connected to database: {os.path.basename(self.db_path)}")
            return True
        except Exception as e:
            print(f"Database connection error: {e}")
            messagebox.showerror("Database Error", f"Could not connect to database: {e}")
            return False

    def select_batch_from_db(self):
        """Select an existing batch from the database to start swiping"""
        if not self.ensure_db_connection():
            messagebox.showerror("Error", "Please connect to a database first.")
            return
            
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get all available batches from the database
            cursor.execute("""
                SELECT DISTINCT batch_name FROM games
                ORDER BY batch_name
            """)
            
            batches = cursor.fetchall()
            
            if not batches:
                messagebox.showinfo("No Batches", "No game batches found in database. Please import a CSV file first.")
                return
                
            # Create a simple dialog to select a batch
            batch_window = tk.Toplevel(self.root)
            batch_window.title("Select Batch")
            batch_window.geometry("300x400")
            batch_window.transient(self.root)
            batch_window.grab_set()
            
            tk.Label(batch_window, text="Select a batch to swipe:", font=('Arial', 12)).pack(pady=10)
            
            # Create a listbox with all batches
            batch_listbox = tk.Listbox(batch_window, width=40, height=15)
            batch_listbox.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)
            
            for i, (batch_name,) in enumerate(batches):
                batch_listbox.insert(tk.END, batch_name)
                
            # Add a scrollbar
            scrollbar = tk.Scrollbar(batch_listbox)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            batch_listbox.config(yscrollcommand=scrollbar.set)
            scrollbar.config(command=batch_listbox.yview)
            
            def on_select():
                if batch_listbox.curselection():
                    selected_index = batch_listbox.curselection()[0]
                    selected_batch = batches[selected_index][0]
                    batch_window.destroy()
                    self.load_batch_from_db(selected_batch)
                else:
                    messagebox.showinfo("Selection Required", "Please select a batch.")
            
            select_button = tk.Button(batch_window, text="Select", command=on_select,
                                     width=15, bg='#4CAF50', fg='white', font=('Arial', 10))
            select_button.pack(pady=15)
            
            cancel_button = tk.Button(batch_window, text="Cancel", command=batch_window.destroy,
                                     width=15, bg='#f44336', fg='white', font=('Arial', 10))
            cancel_button.pack(pady=5)
            
    def load_batch_from_db(self, batch_name):
        """Load a batch from the database and start swiping"""
        if not self.ensure_db_connection():
            return
            
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get all games for this batch
            cursor.execute('''
                SELECT * FROM games WHERE batch_name = ? 
                ORDER BY id
            ''', (batch_name,))
            
            self.entries = [dict(zip([col[0] for col in cursor.description], row))
                          for row in cursor.fetchall()]
            
            if not self.entries:
                messagebox.showerror("Error", f"No games found in batch: {batch_name}")
                return
                
            self.input_filename = batch_name
            
            # Initialize or load progress
            cursor.execute('''
                INSERT OR IGNORE INTO progress (user_name, batch_name, current_index)
                VALUES (?, ?, 0)
            ''', (self.user_name, batch_name))
            
            # Check for existing progress
            cursor.execute('''
                SELECT current_index FROM progress
                WHERE user_name = ? AND batch_name = ?
            ''', (self.user_name, batch_name))
            
            result = cursor.fetchone()
            if result:
                self.current_index = result[0]
                
            conn.commit()
            
            # Create the UI for swiping
            self.create_ui()
            
            # Show message about progress
            if self.current_index > 0:
                messagebox.showinfo("Resuming Progress", 
                                   f"Resuming from game {self.current_index + 1} of {len(self.entries)}")
            
            # Update UI with current game
            if self.current_index < len(self.entries):
                self.update_ui()
            else:
                messagebox.showinfo("Batch Complete", "You've already completed this batch.")
                self.back_to_main_menu()

    def import_additional_dataset(self):
        if not self.ensure_db_connection():
            return
            
        file_path = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv")])
        if not file_path:
            return
            
        batch_name = simpledialog.askstring("Batch Name", "Enter a name for this batch of games:",
                                          initialvalue=os.path.splitext(os.path.basename(file_path))[0])
        if not batch_name:
            return
            
        imported_count = 0
        duplicate_count = 0
        
        with open(file_path, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                for row in reader:
                    try:
                        cursor.execute('''
                            INSERT INTO games 
                            (name, developers, release_date, steam_page_url, batch_name)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (
                            row['name'],
                            row['developers'],
                            row['release_date'],
                            row['steam_page_url'],
                            batch_name
                        ))
                        imported_count += 1
                    except sqlite3.IntegrityError:
                        duplicate_count += 1
                
                conn.commit()
        
        messagebox.showinfo("Import Complete", 
                            f"Imported {imported_count} games, skipped {duplicate_count} duplicates.")
        self.status_label.config(text=f"Imported dataset: {batch_name}")

    def export_new_yes_votes(self):
        if not self.ensure_db_connection():
            return
        
        # Get information about votes to export
        yes_votes = []
        vote_ids = []
        
        try:
            # Use a fresh connection with autocommit disabled for better transaction control
            conn = sqlite3.connect(self.db.db_path)
            cursor = conn.cursor()
            
            print("\n=== EXPORT DEBUG INFO ===")
            
            # Check if exported column exists
            cursor.execute("PRAGMA table_info(votes)")
            columns = [row[1] for row in cursor.fetchall()]
            print(f"Database columns in votes table: {columns}")
            
            # Get all yes votes that haven't been exported yet
            query = '''
                SELECT g.*, v.id as vote_id, v.timestamp
                FROM games g
                JOIN votes v ON g.id = v.game_id
                WHERE v.vote = 1 AND v.user_name = ? AND v.exported = 0
                ORDER BY v.timestamp
            '''
            
            cursor.execute(query, (self.user_name,))
            yes_votes = cursor.fetchall()
            
            if not yes_votes:
                messagebox.showinfo("No Votes", "No 'Yes' votes found to export.")
                conn.close()
                return
                
            # Prepare data for export
            columns = [col[0] for col in cursor.description]
            yes_votes_dicts = [dict(zip(columns, row)) for row in yes_votes]
            vote_ids = [vote['vote_id'] for vote in yes_votes_dicts]
            
            # Show current status of these votes
            vote_ids_str = ', '.join(str(id) for id in vote_ids)
            cursor.execute(f"SELECT id, exported FROM votes WHERE id IN ({vote_ids_str})")
            current_status = cursor.fetchall()
            print(f"Current status of votes to export: {current_status}")
            
            # Get export filename
            export_path = filedialog.asksaveasfilename(
                defaultextension=".csv",
                filetypes=[("CSV Files", "*.csv")],
                initialfile=f"yes_votes_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            )
            
            if not export_path:
                conn.close()
                return
                
            # Export to CSV
            export_fields = ['name', 'developers', 'release_date', 'steam_page_url', 'batch_name', 'timestamp']
            
            with open(export_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=export_fields)
                writer.writeheader()
                for vote in yes_votes_dicts:
                    writer.writerow({k: vote.get(k, '') for k in export_fields})
            
            # Mark votes as exported - direct SQL approach
            print(f"Attempting to mark {len(vote_ids)} votes as exported with IDs: {vote_ids}")
            
            for vote_id in vote_ids:
                try:
                    cursor.execute("UPDATE votes SET exported = 1 WHERE id = ?", (vote_id,))
                    print(f"Updated vote ID {vote_id}, rows affected: {cursor.rowcount}")
                except Exception as e:
                    print(f"Error updating vote ID {vote_id}: {e}")
            
            # Commit changes
            conn.commit()
            
            # Verify updates
            cursor.execute(f"SELECT id, exported FROM votes WHERE id IN ({vote_ids_str})")
            updated_status = cursor.fetchall()
            print(f"Status after update: {updated_status}")
            
            # One more update with standalone connection as a backup approach
            conn2 = sqlite3.connect(self.db.db_path)
            cursor2 = conn2.cursor()
            cursor2.execute(f"UPDATE votes SET exported = 1 WHERE id IN ({vote_ids_str})")
            cursor2.execute(f"SELECT id, exported FROM votes WHERE id IN ({vote_ids_str})")
            final_status = cursor2.fetchall()
            print(f"Final status with direct update: {final_status}")
            conn2.commit()
            conn2.close()
            
            conn.close()
            
            messagebox.showinfo("Export Complete", f"Exported {len(yes_votes)} 'Yes' votes to {export_path}")
            self.status_label.config(text=f"Exported {len(yes_votes)} yes votes")
            
        except Exception as e:
            print(f"Export error: {e}")
            messagebox.showerror("Export Error", f"An error occurred during export: {str(e)}")
            try:
                conn.close()
            except:
                pass

    def read_file(self, filename):
        self.ensure_db_connection()
        self.input_filename = os.path.splitext(os.path.basename(filename))[0]
        
        # Read CSV and insert into database
        with open(filename, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            self.fieldnames = reader.fieldnames
            
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Insert games into database
                for row in reader:
                    cursor.execute('''
                        INSERT OR IGNORE INTO games 
                        (name, developers, release_date, steam_page_url, batch_name)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (
                        row['name'],
                        row['developers'],
                        row['release_date'],
                        row['steam_page_url'],
                        self.input_filename
                    ))
                
                # Get all games for this batch
                cursor.execute('''
                    SELECT * FROM games WHERE batch_name = ? 
                    ORDER BY id
                ''', (self.input_filename,))
                self.entries = [dict(zip([col[0] for col in cursor.description], row))
                              for row in cursor.fetchall()]
                
                # Initialize or load progress
                cursor.execute('''
                    INSERT OR IGNORE INTO progress (user_name, batch_name, current_index)
                    VALUES (?, ?, 0)
                ''', (self.user_name, self.input_filename))
                
                conn.commit()

    @staticmethod
    def initialize_voter():
        voter = SteamGameVoter()
        atexit.register(voter.save_progress)
        return voter

    def swipe_unvoted_games(self):
        """Start swiping on random games that haven't been voted on yet by the current user"""
        if not self.ensure_db_connection():
            messagebox.showerror("Error", "Please connect to a database first.")
            return
            
        # Switch to using a different approach - get one game at a time
        self.random_unvoted_mode = True
        self.entries = []  # Clear any existing entries
        self.current_index = 0
        
        # Preload a batch of games to improve performance
        self.preload_unvoted_games(10)  # Preload 10 games
        
        if hasattr(self, 'game_queue') and self.game_queue:
            # Create the UI for swiping just once
            self.create_ui()
            # Add a label to show we're in random mode
            self.random_mode_label = tk.Label(self.root, text="RANDOM MODE: Swiping unvoted games", 
                                           bg='#E91E63', fg='white', font=('Arial', 10, 'bold'))
            self.random_mode_label.place(relx=0.5, y=5, anchor="n")
            
            # Get the first game from queue and update UI
            self.load_next_from_queue()
        else:
            messagebox.showinfo("No Games", "No unvoted games found in the database.")
    
    def preload_unvoted_games(self, count=5):
        """Preload a batch of unvoted games to improve performance"""
        self.game_queue = []
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            try:
                # Get multiple random games at once - now with more aggressive locking to prevent conflicts
                cursor.execute(f'''
                    SELECT g.* FROM games g
                    WHERE NOT EXISTS (
                        SELECT 1 FROM votes v 
                        WHERE v.game_id = g.id AND v.user_name = ?
                    )
                    ORDER BY RANDOM()
                    LIMIT {count}
                ''', (self.user_name,))
                
                columns = [col[0] for col in cursor.description]
                games = cursor.fetchall()
                
                if not games:
                    return False
                    
                # Convert to list of dictionaries
                self.game_queue = [dict(zip(columns, game)) for game in games]
                print(f"Preloaded {len(self.game_queue)} unvoted games")
                return True
                
            except Exception as e:
                print(f"Error preloading games: {e}")
                return False
    
    def load_next_from_queue(self):
        """Load the next game from the preloaded queue"""
        # If queue is empty or nearly empty, preload more games
        if not hasattr(self, 'game_queue') or len(self.game_queue) < 2:
            # Preload more games if we're running low
            self.preload_unvoted_games(10)
            
        if self.game_queue:
            # Double-check that the first game in queue hasn't been voted on
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                skipped = 0
                
                while self.game_queue:
                    candidate_game = self.game_queue[0]
                    
                    # Check if this game is still unvoted
                    cursor.execute('''
                        SELECT 1 FROM votes 
                        WHERE game_id = ? AND user_name = ?
                    ''', (candidate_game['id'], self.user_name))
                    
                    if cursor.fetchone():
                        # This game has been voted on already, remove it from queue
                        self.game_queue.pop(0)
                        skipped += 1
                        print(f"Skipped already voted game: {candidate_game['name']}")
                    else:
                        # Game is still unvoted, we can use it
                        break
                
                if skipped > 0:
                    print(f"Skipped {skipped} games that were already voted on")
                    # Replenish the queue if we skipped games
                    self.preload_unvoted_games(skipped)
            
            if self.game_queue:
                # Get the next game from the queue
                self.current_game = self.game_queue.pop(0)
                self.entries = [self.current_game]  # For compatibility
                
                # Update UI with the new game
                self.update_ui_fast()
                return True
            else:
                # No more unvoted games
                messagebox.showinfo("All Done", "You've voted on all available games!")
                self.back_to_main_menu()
                return False
        else:
            # No more unvoted games
            messagebox.showinfo("All Done", "You've voted on all available games!")
            self.back_to_main_menu()
            return False
            
    def load_next_unvoted_game(self):
        """Legacy method - now just calls load_next_from_queue"""
        return self.load_next_from_queue()
    
    def update_ui_fast(self):
        """Update UI without recreating everything - much faster"""
        if not hasattr(self, 'entry_label') or not self.entry_label:
            return self.update_ui()
            
        entry = self.current_game if hasattr(self, 'current_game') else self.entries[self.current_index]
        
        # Update only the text content, don't recreate widgets
        self.entry_label.config(
            text=f"Game: {entry['name']}\nDeveloper: {entry['developers']}\nRelease Date: {entry['release_date']}"
        )
        
        if hasattr(self, 'random_unvoted_mode') and self.random_unvoted_mode:
            self.progress_label.config(text=f"Random Mode: {len(self.game_queue)} games queued")
        else:
            self.progress_label.config(text=f"Progress: {self.current_index + 1}/{len(self.entries)}")
        
        # Load web page
        self.root.update()  # Update UI immediately before loading web page
        self.open_webpage(entry['steam_page_url'])
            
    def vote(self, value):
        # In standard mode
        if not hasattr(self, 'random_unvoted_mode') or not self.random_unvoted_mode:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Record the vote
                current_game = self.entries[self.current_index]
                cursor.execute('''
                    INSERT OR REPLACE INTO votes (game_id, user_name, vote, timestamp, exported)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP, 0)
                ''', (current_game['id'], self.user_name, value))
                
                # Update progress
                self.current_index += 1
                cursor.execute('''
                    UPDATE progress 
                    SET current_index = ?
                    WHERE user_name = ? AND batch_name = ?
                ''', (self.current_index, self.user_name, self.input_filename))
                
                conn.commit()

            if self.current_index < len(self.entries):
                self.update_ui_fast()  # Use fast UI update
            else:
                self.process_completed = True
                self.export_results()
                self.close_application()
        else:
            # In random unvoted mode
            current_game = self.current_game
            
            with self.db.get_connection() as conn:
                conn.isolation_level = 'EXCLUSIVE'  # Use transaction isolation for safety
                cursor = conn.cursor()
                
                try:
                    # Begin transaction
                    cursor.execute('BEGIN EXCLUSIVE TRANSACTION')
                    
                    # First check if this game has already been voted on by another user or process
                    cursor.execute('''
                        SELECT id FROM votes 
                        WHERE game_id = ? AND user_name = ?
                    ''', (current_game['id'], self.user_name))
                    
                    existing_vote = cursor.fetchone()
                    
                    if existing_vote:
                        # This game has already been voted on since we loaded it
                        print(f"Game {current_game['name']} was already voted on! Skipping...")
                        messagebox.showinfo("Already Voted", 
                                          f"Game '{current_game['name']}' was already voted on by another session. Skipping to next game.")
                    else:
                        # Record the vote if not already voted
                        cursor.execute('''
                            INSERT INTO votes (game_id, user_name, vote, timestamp, exported)
                            VALUES (?, ?, ?, CURRENT_TIMESTAMP, 0)
                        ''', (current_game['id'], self.user_name, value))
                        print(f"Recorded vote for game {current_game['name']}")
                    
                    # Commit transaction
                    conn.commit()
                except sqlite3.Error as e:
                    # If anything goes wrong, roll back
                    conn.rollback()
                    print(f"Database error when voting: {e}")
                    messagebox.showerror("Vote Error", 
                                       f"Error recording vote: {str(e)}\nSkipping to next game.")
            
            # Get the next game from preloaded queue
            self.load_next_from_queue()
            
    def update_ui(self):
        """Full UI update (slower but more comprehensive)"""
        if hasattr(self, 'update_ui_fast') and hasattr(self, 'entry_label') and self.entry_label:
            return self.update_ui_fast()
            
        if not hasattr(self, 'random_unvoted_mode') or not self.random_unvoted_mode:
            entry = self.entries[self.current_index]
            self.entry_label.config(
                text=f"Game: {entry['name']}\nDeveloper: {entry['developers']}\nRelease Date: {entry['release_date']}"
            )
            self.progress_label.config(text=f"Progress: {self.current_index + 1}/{len(self.entries)}")
            self.open_webpage(entry['steam_page_url'])
        else:
            # Random mode - just show the current game
            entry = self.current_game
            self.entry_label.config(
                text=f"Game: {entry['name']}\nDeveloper: {entry['developers']}\nRelease Date: {entry['release_date']}"
            )
            
            # Show how many games are queued
            queue_count = len(self.game_queue) if hasattr(self, 'game_queue') else 0
            self.progress_label.config(text=f"Random Mode: {queue_count} games queued")
            
            self.open_webpage(entry['steam_page_url'])
            
    def open_webpage(self, url):
        """Load a web page in the browser"""
        if self.driver is None:
            self.initialize_browser()
            
        try:
            # Set a page load timeout to prevent hanging
            self.driver.set_page_load_timeout(10)
            self.driver.get(url)
            
            # Wait for the body element to appear (faster than waiting for full page load)
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
        except Exception as e:
            print(f"Error loading web page: {e}")
            # Don't show error dialog as it would interrupt flow

    def save_progress(self):
        """Save current progress to database"""
        try:
            if not hasattr(self, 'db') or not self.db or not hasattr(self, 'current_index') or self.process_completed:
                return
                
            if not hasattr(self, 'input_filename') or not self.input_filename:
                return
                
            if not hasattr(self, 'user_name') or not self.user_name:
                return
                
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE progress 
                    SET current_index = ?
                    WHERE user_name = ? AND batch_name = ?
                ''', (self.current_index, self.user_name, self.input_filename))
                conn.commit()
        except Exception as e:
            print(f"Error saving progress: {e}")
            
    def load_progress(self):
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT current_index FROM progress
                WHERE user_name = ? AND batch_name = ?
            ''', (self.user_name, self.input_filename))
            result = cursor.fetchone()
            
            if result and result[0] > 0:
                self.current_index = result[0]
                messagebox.showinfo("Progress Loaded", f"Resuming from game {self.current_index + 1}")
                return True
        return False

    def export_results(self):
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get all votes for the current batch
            cursor.execute('''
                SELECT g.*, v.vote
                FROM games g
                LEFT JOIN votes v ON g.id = v.game_id AND v.user_name = ?
                WHERE g.batch_name = ?
            ''', (self.user_name, self.input_filename))
            
            results = cursor.fetchall()
            columns = [col[0] for col in cursor.description]
            
            # Separate into yes/no votes
            yes_votes = []
            no_votes = []
            
            for row in results:
                game_dict = dict(zip(columns, row))
                if game_dict['vote'] == 1:
                    yes_votes.append(game_dict)
                elif game_dict['vote'] == 0:
                    no_votes.append(game_dict)

            # Export to CSV files
            data_folder = Path('data')
            data_folder.mkdir(exist_ok=True)
            
            export_fields = ['name', 'developers', 'release_date', 'steam_page_url']
            
            def save_votes(filename, votes):
                with open(data_folder / filename, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=export_fields)
                    writer.writeheader()
                    for vote in votes:
                        writer.writerow({k: vote[k] for k in export_fields})
            
            yes_filename = f"{self.input_filename}_yes_votes.csv"
            no_filename = f"{self.input_filename}_no_votes.csv"
            
            save_votes(yes_filename, yes_votes)
            save_votes(no_filename, no_votes)
            
            messagebox.showinfo(
                "Results Saved",
                f"Results have been saved to '{yes_filename}' and '{no_filename}' in {data_folder.absolute()}"
            )

    def initialize_browser(self):
        if self.driver is None:
            browser_choice = self.browser_var.get()
            if browser_choice == "Chrome":
                options = ChromeOptions()
                self.driver = webdriver.Chrome(options=options)
            elif browser_choice == "Firefox":
                options = FirefoxOptions()
                self.driver = webdriver.Firefox(options=options)
            elif browser_choice == "Edge":
                options = EdgeOptions()
                self.driver = webdriver.Edge(options=options)
            else:
                raise ValueError(f"Unsupported browser choice: {browser_choice}")
            
            self.driver.maximize_window()
    
    def change_browser(self):
        if self.driver:
            self.driver.quit()
        self.driver = None
        self.update_ui()  # This will cause the new browser to be initialized

    def close_application(self):
        if self.driver:
            self.driver.quit()
        # Save config before closing
        self.save_config()
        self.root.quit()
        self.root.destroy()

    def create_ui(self):
        # Clear the root window first
        for widget in self.root.winfo_children():
            widget.destroy()
            
        self.root.configure(bg='#f0f0f0')
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        main_frame = tk.Frame(self.root, bg='#f0f0f0')
        main_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        main_frame.grid_rowconfigure(0, weight=1)
        main_frame.grid_columnconfigure(0, weight=1)

        # Game info frame
        info_frame = tk.Frame(main_frame, bg='white', bd=2, relief=tk.RAISED)
        info_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 10))

        self.entry_label = tk.Label(info_frame, text="", wraplength=340, justify="center", bg='white', font=('Arial', 12))
        self.entry_label.pack(pady=10, expand=True)

        self.progress_label = tk.Label(main_frame, text="", bg='#f0f0f0', font=('Arial', 10))
        self.progress_label.grid(row=1, column=0, sticky="ew")

        # Button frame
        button_frame = tk.Frame(main_frame, bg='#f0f0f0')
        button_frame.grid(row=2, column=0, sticky="ew", pady=10)
        button_frame.grid_columnconfigure(0, weight=1)
        button_frame.grid_columnconfigure(2, weight=1)

        # X button (No)
        x_button = tk.Button(button_frame, text="❌", command=lambda: self.vote(False), 
                             font=('Arial', 20), bg='white', fg='red', width=3, height=1)
        x_button.grid(row=0, column=0, sticky="w")

        # Check button (Yes)
        check_button = tk.Button(button_frame, text="✔️", command=lambda: self.vote(True), 
                                 font=('Arial', 20), bg='white', fg='green', width=3, height=1)
        check_button.grid(row=0, column=2, sticky="e")

        # Back to main menu button
        back_button = tk.Button(main_frame, text="Back to Main Menu", 
                               command=self.back_to_main_menu,
                               width=15, bg='#2196F3', fg='white', font=('Arial', 10))
        back_button.grid(row=3, column=0, sticky="ew", pady=(0, 10))

        # Browser selection frame
        browser_frame = tk.Frame(main_frame, bg='#f0f0f0')
        browser_frame.grid(row=4, column=0, sticky="ew")

        tk.Label(browser_frame, text="Browser:", bg='#f0f0f0', font=('Arial', 10)).pack(side=tk.LEFT, padx=5)

        browsers = [("Chrome", "Chrome"), ("Firefox", "Firefox"), ("Edge", "Edge")]
        for text, value in browsers:
            tk.Radiobutton(browser_frame, text=text, variable=self.browser_var, value=value, 
                           command=self.change_browser, bg='#f0f0f0', font=('Arial', 10)).pack(side=tk.LEFT, padx=5)
        
        # Always on top checkbutton
        always_on_top_check = tk.Checkbutton(main_frame, text="Keep this window in foreground", variable=self.always_on_top_var,
                                             command=self.toggle_always_on_top, bg='#f0f0f0', font=('Arial', 10))
        always_on_top_check.grid(row=5, column=0, sticky="w", pady=(10, 0))

    def back_to_main_menu(self):
        if self.driver:
            self.driver.quit()
            self.driver = None
            
        # Reset random mode flag if it exists
        if hasattr(self, 'random_unvoted_mode'):
            self.random_unvoted_mode = False
        
        self.save_progress()
        self.create_initial_ui()

    def toggle_always_on_top(self):
        self.root.attributes('-topmost', self.always_on_top_var.get())
        # Save the setting to config
        self.save_config()

    def select_file(self):
        if not self.ensure_db_connection():
            return
            
        file_path = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv")])
        if file_path:
            self.read_file(file_path)
            if self.entries:
                self.create_ui()
                if not self.load_progress():
                    self.current_index = 0
                self.update_ui()
            else:
                messagebox.showerror("Error", "No entries found in the selected file.")
        else:
            messagebox.showinfo("Info", "No file selected.")

    def wipe_votes_with_confirmation(self):
        """Wipe all votes and games from the database after confirmation"""
        if not self.ensure_db_connection():
            messagebox.showerror("Error", "Please connect to a database first.")
            return
            
        # Create a confirmation dialog
        confirm_window = tk.Toplevel(self.root)
        confirm_window.title("Confirm Complete Wipe")
        confirm_window.geometry("450x300")
        confirm_window.transient(self.root)
        confirm_window.grab_set()
        
        # Warning icon and message
        warning_frame = tk.Frame(confirm_window, bg='#ffebee')
        warning_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        warning_label = tk.Label(
            warning_frame, 
            text="⚠️ WARNING: This will delete ALL votes AND games from the database!\n\nThis will completely reset the database.\nThis action cannot be undone.\n\nConsider exporting your votes before wiping.",
            bg='#ffebee', fg='#b71c1c',
            font=('Arial', 12),
            wraplength=400,
            justify=tk.CENTER
        )
        warning_label.pack(pady=(20, 30))
        
        # Checkbox for additional confirmation
        confirm_var = tk.BooleanVar(value=False)
        confirm_check = tk.Checkbutton(
            warning_frame, 
            text="I understand this will permanently delete all votes and games",
            variable=confirm_var,
            bg='#ffebee'
        )
        confirm_check.pack(pady=(0, 20))
        
        # Buttons frame
        button_frame = tk.Frame(warning_frame, bg='#ffebee')
        button_frame.pack(pady=(0, 10))
        
        def on_cancel():
            confirm_window.destroy()
            
        def on_confirm():
            if confirm_var.get():
                confirm_window.destroy()
                self.wipe_database()
            else:
                messagebox.showinfo("Confirmation Required", "Please check the confirmation box to proceed.")
        
        cancel_button = tk.Button(
            button_frame, 
            text="Cancel", 
            command=on_cancel,
            width=10, 
            bg='#4CAF50', 
            fg='white'
        )
        cancel_button.pack(side=tk.LEFT, padx=10)
        
        wipe_button = tk.Button(
            button_frame, 
            text="Wipe Database", 
            command=on_confirm,
            width=15, 
            bg='#F44336', 
            fg='white'
        )
        wipe_button.pack(side=tk.RIGHT, padx=10)
        
    def wipe_database(self):
        """Completely wipe votes and games from the database"""
        try:
            with self.db.get_connection() as conn:
                conn.isolation_level = 'EXCLUSIVE'  # Use transaction isolation
                cursor = conn.cursor()
                
                try:
                    # Begin transaction
                    cursor.execute('BEGIN EXCLUSIVE TRANSACTION')
                    
                    # Get counts before wiping
                    cursor.execute("SELECT COUNT(*) FROM votes")
                    vote_count = cursor.fetchone()[0]
                    
                    cursor.execute("SELECT COUNT(*) FROM games")
                    game_count = cursor.fetchone()[0]
                    
                    # Delete everything
                    cursor.execute("DELETE FROM votes")
                    cursor.execute("DELETE FROM games")
                    cursor.execute("DELETE FROM progress")
                    
                    # Commit the transaction
                    conn.commit()
                    
                    messagebox.showinfo(
                        "Database Wiped", 
                        f"Successfully wiped the database:\n• Deleted {vote_count} votes\n• Deleted {game_count} games\n• Reset all progress\n\nThe database is now empty and ready for new games."
                    )
                    self.status_label.config(text=f"Wiped database: {vote_count} votes, {game_count} games")
                    print(f"Wiped database: {vote_count} votes, {game_count} games")
                    
                except sqlite3.Error as e:
                    # If anything goes wrong, roll back
                    conn.rollback()
                    print(f"Database error during wipe: {e}")
                    messagebox.showerror("Wipe Error", f"Error wiping database: {str(e)}")
                    
        except Exception as e:
            print(f"Error wiping database: {e}")
            messagebox.showerror("Error", f"Failed to wipe database: {str(e)}")
            
    def export_and_wipe(self):
        """Export votes and then wipe the database"""
        # First export all votes
        self.export_new_yes_votes()
        
        # Then ask if user wants to wipe the database
        if messagebox.askyesno("Wipe Database", "Export complete. Do you want to completely wipe the database now (delete all votes AND games)?"):
            self.wipe_votes_with_confirmation()

# Main program
if __name__ == "__main__":
    try:
        voter = SteamGameVoter.initialize_voter()
        voter.root.mainloop()
    except Exception as e:
        print(f"An error occurred: {e}")
        # This will trigger the atexit function to save progress