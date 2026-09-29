import 'package:flutter/material.dart';

import 'panels/camera_panel.dart';
import 'panels/export_panel.dart';
import 'panels/results_panel.dart';

/// ATLAS-BC entry point (Raspberry Pi / edge deployment).
Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const AtlasBcApp());
}

/// Root Material app with ATLAS-BC theme and phone-sized demo frame.
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

/// Three-step workflow: capture both breasts → validate AI → export PDF/email.
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

  /// Clears the in-memory session for the next patient.
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
                _currentScanId = null;
                _isProcessingAI = false;
                _aiLeftResult = null;
                _aiRightResult = null;
                _aiCombinedResult = null;
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

  /// Assigns `_currentScanId` before the user opens the live preview.
  void _ensureScanId() {
    if (_currentScanId != null) return;
    setState(() {
      _currentScanId = 'SCAN-${_scanCounter.toString().padLeft(4, '0')}';
      _scanCounter++;
    });
  }

  Map<String, String> _resultFromScan(Map<String, dynamic> scan) {
    return {
      'classification': scan['classification']?.toString() ?? '--',
      'confidence': scan['confidence']?.toString() ?? '--',
      'recommendation': scan['recommendation']?.toString() ?? '',
    };
  }

  /// Uses the higher BI-RADS number as the bilateral summary (prototype rule).
  Map<String, String>? _combineBilateral(
    Map<String, String>? left,
    Map<String, String>? right,
  ) {
    if (left == null || right == null) return null;

    int score(String? label) {
      if (label == null) return 0;
      final match = RegExp(r'(\d+)').firstMatch(label);
      return match != null ? int.parse(match.group(1)!) : 0;
    }

    final dominant =
        score(right['classification']) >= score(left['classification'])
            ? right
            : left;
    final other = dominant == right ? left : right;

    return {
      'classification': dominant['classification'] ?? '--',
      'confidence': dominant['confidence'] ?? '--',
      'recommendation': dominant['recommendation']?.isNotEmpty == true
          ? dominant['recommendation']!
          : 'Dominant finding: ${dominant['classification']}. '
              'Contralateral: ${other['classification']}.',
    };
  }

  void _refreshAiSummaries() {
    Map<String, String>? left;
    Map<String, String>? right;
    for (final scan in _scanData) {
      if (scan['side'] == 'Left') left = _resultFromScan(scan);
      if (scan['side'] == 'Right') right = _resultFromScan(scan);
    }
    _aiLeftResult = left;
    _aiRightResult = right;
    _aiCombinedResult = _combineBilateral(left, right);
  }

  @override
  Widget build(BuildContext context) {
    final List<Widget> panels = [
      CameraPanel(
        scanData: _scanData,
        currentScanId: _currentScanId,
        onEnsureScanId: _ensureScanId,
        onReset: () => setState(() {
          _scanData.clear();
          _currentScanId = null;
          _aiLeftResult = null;
          _aiRightResult = null;
          _aiCombinedResult = null;
        }),
        onImageCaptured: (imagePath, side, view, aiResult) async {
          setState(() {
            _scanData.add({
              'image_path': imagePath,
              'side': side,
              'view': view,
              ...aiResult,
            });
          });

          if (_scanData.length >= 2) {
            setState(() {
              _currentIndex = 1;
              _isProcessingAI = true;
            });
            await Future.delayed(const Duration(milliseconds: 800));
            if (mounted) {
              setState(() {
                _isProcessingAI = false;
                _refreshAiSummaries();
              });
            }
          } else if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text(
                  'Captured $side breast. Please capture the other side.',
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
                  'Please complete both left and right scans first.',
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
