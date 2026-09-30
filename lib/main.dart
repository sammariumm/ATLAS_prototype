import 'dart:io';
import 'package:flutter/material.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import 'panels/camera_panel.dart';
import 'panels/results_panel.dart';
import 'panels/export_panel.dart';
import 'services/database_helper.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  
  if (Platform.isWindows || Platform.isLinux) {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
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
      ),
      home: const Scaffold(
        backgroundColor: Colors.black87,
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
  String _currentScanId = 'SCAN-0001';

  // CHANGED: Tracking views (CC/MLO) instead of sides
  Map<String, String>? _aiCCResult;
  Map<String, String>? _aiMLOResult;
  Map<String, String>? _aiCombinedResult;

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
      _aiCCResult = null;
      _aiMLOResult = null;
      _aiCombinedResult = null;
      _currentIndex = 0; 
      
      _scanCounter++;
      _currentScanId = 'SCAN-${_scanCounter.toString().padLeft(4, '0')}';
    });
  }

  void _handleImageCaptured(String imagePath, String side, String view, Map<String, String> aiResult) {
    setState(() {
      _scanData.add({'image_path': imagePath, 'side': side, 'view': view});
      
      // CHANGED: Save AI results based on View
      if (view == 'CC') _aiCCResult = aiResult;
      if (view == 'MLO') _aiMLOResult = aiResult;

      // Trigger completion when we have 2 images (CC and MLO)
      if (_scanData.length >= 2) {
        _aiCombinedResult = {
          'classification': (_aiCCResult?['classification'] == 'BI-RADS 4' || _aiMLOResult?['classification'] == 'BI-RADS 4') ? 'BI-RADS 4' : 'BI-RADS 1',
          'confidence': _aiCCResult?['confidence'] ?? '90%',
          'recommendation': 'Unilateral analysis complete. Consult healthcare provider for next steps.',
        };
        _currentIndex = 1; 
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final List<Widget> panels = [
      CameraPanel(
        scanData: _scanData,
        currentScanId: _currentScanId, 
        onImageCaptured: _handleImageCaptured,
        onReset: _resetSession,
      ),
      ResultsPanel(
        scanData: _scanData,
        scanId: _currentScanId,
        ccResult: _aiCCResult,    // CHANGED
        mloResult: _aiMLOResult,  // CHANGED
        combinedResult: _aiCombinedResult,
        onNewPatient: _resetSession,
      ),
      ExportPanel(
        scanData: _scanData,
        scanId: _currentScanId,
        ccResult: _aiCCResult,    // CHANGED
        mloResult: _aiMLOResult,  // CHANGED
        combinedResult: _aiCombinedResult,
        onNewPatient: _resetSession,
      ),
    ];

    return Scaffold(
      body: IndexedStack(index: _currentIndex, children: panels),
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
      ),
    );
  }
}