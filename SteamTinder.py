import tkinter as tk
from tkinter import messagebox, filedialog
import csv
import json
import os
import atexit
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

class SteamGameVoter:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Steam Tinder")
        self.root.geometry("400x300")
        self.entries = []
        self.results = {}
        self.current_index = 0
        self.fieldnames = []
        self.driver = None
        self.input_filename = ""
        self.process_completed = False
        self.browser_var = tk.StringVar(value="Chrome")
        self.always_on_top_var = tk.BooleanVar(value=False)

    def __del__(self):
        if self.driver:
            self.driver.quit()
        self.save_progress()

    def read_file(self, filename):
        self.input_filename = os.path.splitext(os.path.basename(filename))[0]
        with open(filename, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            self.entries = list(reader)
            self.fieldnames = reader.fieldnames

    def initialize_voter():
        voter = SteamGameVoter()
        atexit.register(voter.save_progress)
        return voter

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

    def open_webpage(self, url):
        if self.driver is None:
            self.initialize_browser()
        self.driver.get(url)
        # Wait for the page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

    def vote(self, value):
        self.results[self.current_index] = value
        self.current_index += 1
        if self.current_index < len(self.entries):
            self.update_ui()
        else:
            self.save_results()
            self.process_completed = True
            self.delete_progress_file()

    def update_ui(self):
        entry = self.entries[self.current_index]
        self.entry_label.config(text=f"Game: {entry['name']}\nDeveloper: {entry['developers']}\nRelease Date: {entry['release_date']}")
        self.progress_label.config(text=f"Progress: {self.current_index + 1}/{len(self.entries)}")
        self.open_webpage(entry['steam_page_url'])

    def delete_progress_file(self):
        if os.path.exists('progress.json'):
            os.remove('progress.json')
            print("Progress file deleted.")

    def save_results(self):
        yes_votes = [self.entries[i] for i, vote in self.results.items() if vote]
        no_votes = [self.entries[i] for i, vote in self.results.items() if not vote]

        data_folder = 'data'
        os.makedirs(data_folder, exist_ok=True)

        yes_filename = f"{self.input_filename}_yes_votes.csv"
        no_filename = f"{self.input_filename}_no_votes.csv"
        
        self.save_csv(os.path.join(data_folder, yes_filename), yes_votes)
        self.save_csv(os.path.join(data_folder, no_filename), no_votes)

        messagebox.showinfo("Results Saved", f"Results have been saved to 'yes_votes.csv' and 'no_votes.csv' in {os.path.abspath(data_folder)}")
        self.close_application()
    
    def close_application(self):
        if self.driver:
            self.driver.quit()
        self.root.quit()
        self.root.destroy()

    def save_csv(self, filename, data):
        with open(filename, 'w', newline='', encoding='utf-8') as file:
            writer = csv.DictWriter(file, fieldnames=self.fieldnames)
            writer.writeheader()
            writer.writerows(data)

    def save_progress(self):
        if self.process_completed:
            return
        progress = {
            'current_index': self.current_index,
            'results': self.results
        }
        with open('progress.json', 'w') as f:
            json.dump(progress, f)
        messagebox.showinfo("Progress Saved", "Progress has been saved.")

    def load_progress(self):
        if os.path.exists('progress.json'):
            with open('progress.json', 'r') as f:
                progress = json.load(f)
            self.current_index = progress['current_index']
            self.results = {int(k): v for k, v in progress['results'].items()}
            messagebox.showinfo("Progress Loaded", "Progress has been loaded.")
            return True
        return False

    def create_ui(self):
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

        save_button = tk.Button(main_frame, text="Save Progress", command=self.save_progress, 
                                width=15, bg='#4CAF50', fg='white', font=('Arial', 10))
        save_button.grid(row=3, column=0, sticky="ew", pady=(0, 10))

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

    def toggle_always_on_top(self):
        self.root.attributes('-topmost', self.always_on_top_var.get())

    def select_file(self):
        file_path = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv")])
        if file_path:
            self.read_file(file_path)
            if self.entries:
                self.create_ui()
                if not self.load_progress():
                    self.current_index = 0
                self.update_ui()
                self.root.mainloop()
            else:
                messagebox.showerror("Error", "No entries found in the selected file.")
        else:
            messagebox.showinfo("Info", "No file selected. Exiting.")

# Main program


if __name__ == "__main__":
    try:
        voter = SteamGameVoter.initialize_voter()
        voter.select_file()
    except Exception as e:
        print(f"An error occurred: {e}")
        # This will trigger the atexit function to save progress