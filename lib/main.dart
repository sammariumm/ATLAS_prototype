import 'package:flutter/material.dart';
<<<<<<< Updated upstream
import 'package:camera/camera.dart';
=======
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
>>>>>>> Stashed changes

import 'panels/camera_panel.dart';
import 'panels/results_panel.dart';
import 'panels/export_panel.dart';
import 'services/database_helper.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
<<<<<<< Updated upstream
  try {
    cameras = await availableCameras();
  } catch (e) {
    debugPrint('Error initializing cameras: $e');
  }
=======
  
  if (Platform.isWindows || Platform.isLinux) {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  }

>>>>>>> Stashed changes
  runApp(const AtlasBcApp());
}

class AtlasBcApp extends StatelessWidget {
  const AtlasBcApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'ATLAS-BC',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        scaffoldBackgroundColor: const Color(0xFFF8FAFC),
        primaryColor: const Color(0xFF134E4A),
<<<<<<< Updated upstream
        appBarTheme: const AppBarTheme(
          backgroundColor: Color(0xFF134E4A),
          centerTitle: true,
          titleTextStyle: TextStyle(
            color: Colors.white,
            fontSize: 20,
            fontWeight: FontWeight.bold,
          ),
          iconTheme: IconThemeData(color: Colors.white),
        ),
      ),
      home: const Scaffold(
        backgroundColor: Colors.black,
=======
      ),
      home: const Scaffold(
        backgroundColor: Colors.black87,
>>>>>>> Stashed changes
        body: Center(
          child: SizedBox(
            width: 480, 
            height: 800, 
            child: ClipRect(child: MainLayout()),
          ),
        ),
      ),
    );
  }
}

class MainLayout extends StatefulWidget {
  const MainLayout({super.key});

  @override
  State<MainLayout> createState() => _MainLayoutState();
}

class _MainLayoutState extends State<MainLayout> {
  int _currentIndex = 0;
  final List<Map<String, dynamic>> _scanData = [];
<<<<<<< Updated upstream

  int _scanCounter = 1;
  String? _currentScanId;

  bool _isProcessingAI = false;
=======
  int _scanCounter = 1;
  String _currentScanId = 'SCAN-0001'; // Default, gets updated in initState
>>>>>>> Stashed changes

  Map<String, String>? _aiLeftResult;
  Map<String, String>? _aiRightResult;
  Map<String, String>? _aiCombinedResult;

<<<<<<< Updated upstream
  // New Patient logic: clears all state data completely
  void _startNewPatient() {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Start New Patient?'),
        content: const Text(
          'This will clear all current unsaved images and AI results. Continue?',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel', style: TextStyle(color: Colors.grey)),
          ),
          TextButton(
            onPressed: () {
              Navigator.pop(context);
              setState(() {
                _scanData.clear();
                _currentIndex = 0;
                _isProcessingAI = false;
                _aiLeftResult = null;
                _aiRightResult = null;
                _aiCombinedResult = null;
                // Next capture will auto-generate a new ID
              });
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(
                  content: Text('New patient profile started.'),
                  backgroundColor: Color(0xFF0D9488),
                ),
              );
            },
            child: const Text(
              'Start New',
              style: TextStyle(
                color: Color(0xFF0D9488),
                fontWeight: FontWeight.bold,
              ),
            ),
          ),
        ],
      ),
    );
=======
  @override
  void initState() {
    super.initState();
    _loadLastScanId();
  }

  Future<void> _loadLastScanId() async {
    try {
      final lastScanId = await DatabaseHelper.instance.getLastScanId();
      if (lastScanId != null && lastScanId.startsWith('SCAN-')) {
        final numericString = lastScanId.substring(5);
        final lastCount = int.tryParse(numericString);
        
        if (lastCount != null) {
          setState(() {
            _scanCounter = lastCount + 1; 
            _currentScanId = 'SCAN-${_scanCounter.toString().padLeft(4, '0')}';
          });
        }
      }
    } catch (e) {
      debugPrint('Could not load previous Scan ID: $e');
    }
  }

  void _resetSession() {
    setState(() {
      _scanData.clear();
      _aiLeftResult = null;
      _aiRightResult = null;
      _aiCombinedResult = null;
      _currentIndex = 0; 
      
      // Advance counter to prevent overwriting discarded patient folders
      _scanCounter++;
      _currentScanId = 'SCAN-${_scanCounter.toString().padLeft(4, '0')}';
    });
  }

  void _handleImageCaptured(String imagePath, String side, String view, Map<String, String> aiResult) {
    setState(() {
      _scanData.add({'image_path': imagePath, 'side': side, 'view': view});
      if (side == 'Left') _aiLeftResult = aiResult;
      if (side == 'Right') _aiRightResult = aiResult;

      if (_scanData.length >= 2) {
        _aiCombinedResult = {
          'classification': (_aiLeftResult?['classification'] == 'BI-RADS 4' || _aiRightResult?['classification'] == 'BI-RADS 4') ? 'BI-RADS 4' : 'BI-RADS 1',
          'confidence': _aiRightResult?['confidence'] ?? '90%',
          'recommendation': 'Mock bilateral analysis complete. Consult healthcare provider for next steps.',
        };
        _currentIndex = 1; 
      }
    });
>>>>>>> Stashed changes
  }

  @override
  Widget build(BuildContext context) {
    final List<Widget> panels = [
      CameraPanel(
        scanData: _scanData,
<<<<<<< Updated upstream
        // Reset current scans logic
        onReset: () => setState(() => _scanData.clear()),
        onImageCaptured: (image, side, view) async {
          setState(() {
            if (_scanData.isEmpty) {
              _currentScanId =
                  'SCAN-${_scanCounter.toString().padLeft(4, '0')}';
              _scanCounter++;
            }
            _scanData.add({'image': image, 'side': side, 'view': view});
          });

          if (_scanData.length >= 2) {
            setState(() {
              _currentIndex = 1;
              _isProcessingAI = true;
            });
            await Future.delayed(const Duration(seconds: 2));

            if (mounted) {
              setState(() {
                _isProcessingAI = false;
                _aiLeftResult = {
                  'classification': 'BI-RADS 1',
                  'confidence': '95%',
                  'recommendation': 'Negative. Routine screening.',
                };
                _aiRightResult = {
                  'classification': 'BI-RADS 4',
                  'confidence': '88%',
                  'recommendation': 'Suspicious abnormality.',
                };
                _aiCombinedResult = {
                  'classification': 'BI-RADS 4',
                  'confidence': '88%',
                  'recommendation': 'Biopsy recommended for the Right breast based on bilateral analysis.',
                };
              });
            }
          } else {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text(
                  'Captured $side Breast. Please capture the other side.',
                ),
                backgroundColor: const Color(0xFF0D9488),
              ),
            );
          }
        },
=======
        currentScanId: _currentScanId, // NEW: Passing the ID to the camera
        onImageCaptured: _handleImageCaptured,
        onReset: _resetSession,
>>>>>>> Stashed changes
      ),
      ResultsPanel(
        scanData: _scanData,
        scanId: _currentScanId,
<<<<<<< Updated upstream
        isProcessing: _isProcessingAI,
=======
        leftResult: _aiLeftResult,
        rightResult: _aiRightResult,
>>>>>>> Stashed changes
        combinedResult: _aiCombinedResult,
        onNewPatient: _resetSession,
      ),
      ExportPanel(
        scanData: _scanData,
        scanId: _currentScanId,
        leftResult: _aiLeftResult,
        rightResult: _aiRightResult,
        combinedResult: _aiCombinedResult,
        onNewPatient: _resetSession,
      ),
    ];

    return Scaffold(
      body: IndexedStack(index: _currentIndex, children: panels),
<<<<<<< Updated upstream
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _currentIndex,
        onTap: (index) {
          if (index != 0 && _scanData.length < 2) {
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(
                content: Text(
                  'Please complete both Left and Right scans first.',
                ),
              ),
            );
            return;
          }
          setState(() => _currentIndex = index);
        },
        selectedItemColor: const Color(0xFF0D9488),
        unselectedItemColor: const Color(0xFF94A3B8),
        items: const [
          BottomNavigationBarItem(
            icon: Icon(Icons.camera_alt_outlined),
            label: 'Camera',
          ),
          BottomNavigationBarItem(
            icon: Icon(Icons.description_outlined),
            label: 'Results',
          ),
          BottomNavigationBarItem(
            icon: Icon(Icons.download_outlined),
            label: 'Export',
          ),
        ],
=======
      bottomNavigationBar: SizedBox(
        height: 70, 
        child: BottomNavigationBar(
          currentIndex: _currentIndex,
          onTap: (index) => setState(() => _currentIndex = index),
          selectedItemColor: const Color(0xFF0D9488),
          unselectedItemColor: const Color(0xFF94A3B8),
          iconSize: 28,
          selectedFontSize: 12,
          unselectedFontSize: 12,
          items: const [
            BottomNavigationBarItem(icon: Icon(Icons.camera_alt), label: 'Camera'),
            BottomNavigationBarItem(icon: Icon(Icons.analytics), label: 'Results'),
            BottomNavigationBarItem(icon: Icon(Icons.picture_as_pdf), label: 'Export'),
          ],
        ),
>>>>>>> Stashed changes
      ),
    );
  }
}
