import 'package:flutter/material.dart';
import 'dart:io';
import 'package:camera/camera.dart';

import 'panels/camera_panel.dart';
import 'panels/results_panel.dart';
import 'panels/export_panel.dart';

List<CameraDescription> cameras = [];

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  try {
    // Only call availableCameras() if NOT running on Linux desktop
    if (!Platform.isLinux) {
      cameras = await availableCameras();
    } else {
      debugPrint('Running on Linux: Bypassing native camera initialization.');
    }
  } catch (e) {
    debugPrint('Error initializing cameras: $e');
  }
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

  int _scanCounter = 1;
  String? _currentScanId;

  bool _isProcessingAI = false;

  Map<String, String>? _aiLeftResult;
  Map<String, String>? _aiRightResult;
  Map<String, String>? _aiCombinedResult;

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
  }

  @override
  Widget build(BuildContext context) {
    final List<Widget> panels = [
      CameraPanel(
        scanData: _scanData,
        currentScanId: _currentScanId, // <--- Added this required parameter
        onReset: () => setState(() => _scanData.clear()),
        onImageCaptured: (imagePath, side, view, aiResult) async { // <--- Updated parameters to accept aiResult
          setState(() {
            if (_scanData.isEmpty) {
              _currentScanId =
                  'SCAN-${_scanCounter.toString().padLeft(4, '0')}';
              _scanCounter++;
            }
            // Save the captured file path and scan info
            _scanData.add({'image': imagePath, 'side': side, 'view': view});
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
                // You can assign your AI results here or use the aiResult passed from the panel
                _aiLeftResult = aiResult; 
                _aiRightResult = aiResult;
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
      ),
      ResultsPanel(
        scanData: _scanData,
        scanId: _currentScanId,
        isProcessing: _isProcessingAI,
        combinedResult: _aiCombinedResult,
      ),
      ExportPanel(
        scanData: _scanData,
        scanId: _currentScanId,
        leftResult: _aiLeftResult,
        rightResult: _aiRightResult,
        combinedResult: _aiCombinedResult,
      ),
    ];

    return Scaffold(
      appBar: AppBar(
        title: const Text('ATLAS-BC'),
        actions: [
          IconButton(
            icon: const Icon(Icons.person_add_alt_1),
            tooltip: 'New Patient',
            onPressed: _startNewPatient,
          ),
        ],
      ),
      body: IndexedStack(index: _currentIndex, children: panels),
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
      ),
    );
  }
}
