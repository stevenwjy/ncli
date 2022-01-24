# frozen_string_literal: true

require 'kindle_highlights'

# Function to remove invalid symbols from filenames
def sanitize_filename(filename)
  # Bad as defined by wikipedia: https://en.wikipedia.org/wiki/Filename#Reserved_characters_and_words
  # Also have to escape the backslash
  bad_chars = ['/', '\\', '?', '%', '*', ':', '|', '"', '<', '>', '.', ' ']
  bad_chars.each do |bad_char|
    filename.gsub!(bad_char, '_')
  end
  filename
end

kindle = KindleHighlights::Client.new( # Add amazon login details below
  email_address: 'email@example.com',
  password: 'password'
)

# Folder you want to store the txt files (in markdown format) in...
folder = File.expand_path('~/Path/to/your/directory')

kindle.books.each do |book|
  fname = "#{folder}/#{sanitize_filename(book.title)}.txt"
  print "#{book.title}\n" # Print name of Book to console so you can track progress
  bookfile = File.open(fname, 'w')
  bookfile.puts "# #{book.title} by #{book.author}\n" # Header of the Book Title and Author
  book.highlights_from_amazon.each do |highlight|
    # Insert Highlighted Text and the Page Number
    bookfile.puts "#{highlight.text} _#{highlight.page}_\n"
    if highlight.note.present?
      # If there's a Note attached to the highlight add this below the highlighted text
      bookfile.puts "**Note:**  #{highlight.note}\n"
    end
    # Add a link to the highlight in the Kindle App
    bookfile.puts "\n[Open in Kindle App](kindle://book?action=open&asin=#{book.asin}&location=#{highlight.location})\n"
  end

  bookfile.close
end
