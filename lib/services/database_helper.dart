import 'dart:io';
import 'package:path/path.dart';
import 'package:sqflite/sqflite.dart';
import 'package:path_provider/path_provider.dart';

class DatabaseHelper {
  static final DatabaseHelper instance = DatabaseHelper._init();
  
  // Track two separate database instances
  Database? _metadataDb;
  Database? _imagesDb;
  
  DatabaseHelper._init();

  // Getter for the Metadata Database
  Future<Database> get metadataDb async {
    if (_metadataDb != null) return _metadataDb!;
    _metadataDb = await _initDB('atlas_metadata.db', _createMetadataDB);
    return _metadataDb!;
  }

  // Getter for the Images Database
  Future<Database> get imagesDb async {
    if (_imagesDb != null) return _imagesDb!;
    _imagesDb = await _initDB('atlas_images.db', _createImagesDB);
    return _imagesDb!;
  }

  Future<Database> _initDB(String filePath, Future Function(Database, int) onCreate) async {
    final dbPath = await getApplicationDocumentsDirectory();
    final path = join(dbPath.path, filePath);
    return await openDatabase(path, version: 1, onCreate: onCreate);
  }

  // Creates the schema for the Metadata Database
  Future _createMetadataDB(Database db, int version) async {
    await db.execute('''
      CREATE TABLE scans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scan_id TEXT NOT NULL,
        physician_name TEXT,
        left_classification TEXT,
        right_classification TEXT,
        combined_classification TEXT,
        is_accurate INTEGER,
        created_at TEXT NOT NULL
      )
    ''');
  }

  // Creates the schema for the separate Images Database
  Future _createImagesDB(Database db, int version) async {
    await db.execute('''
      CREATE TABLE scan_images (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scan_id TEXT NOT NULL,
        side TEXT NOT NULL,
        view_type TEXT NOT NULL,
        image_path TEXT NOT NULL
      )
    ''');
  }

  /// Inserts data into both databases respectively
  Future<void> saveCompleteScan({
    required String scanId,
    required String physicianName,
    required String leftClassification,
    required String rightClassification,
    required String combinedClassification,
    required bool isAccurate,
    required List<Map<String, dynamic>> scanData,
  }) async {
    // 1. Open both databases
    final metaDb = await instance.metadataDb;
    final imgDb = await instance.imagesDb;
    
    // 2. Save Results to Metadata DB
    await metaDb.insert('scans', {
      'scan_id': scanId,
      'physician_name': physicianName,
      'left_classification': leftClassification,
      'right_classification': rightClassification,
      'combined_classification': combinedClassification,
      'is_accurate': isAccurate ? 1 : 0,
      'created_at': DateTime.now().toIso8601String(),
    });

    // 3. Save Image Paths to Images DB
    for (var scan in scanData) {
      if (scan['image'].path.isNotEmpty) {
        await imgDb.insert('scan_images', {
          'scan_id': scanId,
          'side': scan['side'],
          'view_type': scan['view'],
          'image_path': scan['image'].path,
        });
      }
    }
  }
}