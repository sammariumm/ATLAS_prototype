import 'package:flutter/material.dart';
import 'package:flutter_mjpeg/flutter_mjpeg.dart';
import '../services/backend_service.dart';

class CameraPanel extends StatefulWidget {
  final List<Map<String, dynamic>> scanData;
  final String currentScanId; // <-- NEW
  final Function(String imagePath, String side, String view, Map<String, String> aiResult) onImageCaptured;
  final VoidCallback onReset;

  const CameraPanel({
    super.key, 
    required this.scanData, 
    required this.currentScanId, // <-- NEW 
    required this.onImageCaptured, 
    required this.onReset
  });

  @override
  State<CameraPanel> createState() => _CameraPanelState();
}

class _CameraPanelState extends State<CameraPanel> {
  String? _selectedSide;
  String? _selectedView;
  bool _isProcessing = false;

  void _executeCapture() async {
    if (_selectedSide == null || _selectedView == null) return;
    setState(() => _isProcessing = true);

    try {
      final result = await BackendService.triggerPythonCapture(
        scanId: widget.currentScanId, // <-- NEW: Sent to backend service
        side: _selectedSide!, 
        view: _selectedView!
      );

      final aiData = {
        'classification': result['classification'].toString(),
        'confidence': result['confidence'].toString(),
        'recommendation': result['recommendation'].toString(),
      };

      widget.onImageCaptured(result['image_path'].toString(), _selectedSide!, _selectedView!, aiData);
      setState(() { _selectedSide = null; _selectedView = null; });
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Failed to connect to AI server', style: TextStyle(color: Colors.white)), backgroundColor: Colors.red));
    } finally {
      if (mounted) setState(() => _isProcessing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column( // CHANGED TO COLUMN FOR PORTRAIT
      children: [
        // Top Half: Camera Stream
        Expanded(
          flex: 5,
          child: Container(
            color: Colors.black,
            child: Stack(
              fit: StackFit.expand,
              children: [
                Mjpeg(
                  isLive: true,
                  stream: 'http://127.0.0.1:5000/stream',
                  error: (context, error, stack) => const Center(child: Text('Connecting to Python Camera...', style: TextStyle(color: Colors.white54))),
                ),
                if (_isProcessing)
                  Container(
                    color: Colors.black87,
                    child: const Center(child: Column(mainAxisSize: MainAxisSize.min, children: [CircularProgressIndicator(color: Color(0xFF0D9488)), SizedBox(height: 16), Text('Processing Inference...', style: TextStyle(color: Colors.white, fontSize: 16))])),
                  ),
              ],
            ),
          ),
        ),
        // Bottom Half: Controls
        Expanded(
          flex: 5,
          child: Container(
            color: const Color(0xFF0F172A),
            padding: const EdgeInsets.all(16.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text('SCAN CONFIG', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 18)),
                const SizedBox(height: 12),
                Row(
                  children: ['Left', 'Right'].map((side) => Expanded(
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 4.0),
                      child: ElevatedButton(
                        style: ElevatedButton.styleFrom(backgroundColor: _selectedSide == side ? const Color(0xFF0D9488) : const Color(0xFF334155), padding: const EdgeInsets.symmetric(vertical: 20)),
                        onPressed: () => setState(() => _selectedSide = side),
                        child: Text(side, style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
                      ),
                    ),
                  )).toList(),
                ),
                const SizedBox(height: 12),
                Row(
                  children: ['CC', 'MLO'].map((view) => Expanded(
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 4.0),
                      child: ElevatedButton(
                        style: ElevatedButton.styleFrom(backgroundColor: _selectedView == view ? const Color(0xFF0D9488) : const Color(0xFF334155), padding: const EdgeInsets.symmetric(vertical: 20)),
                        onPressed: () => setState(() => _selectedView = view),
                        child: Text(view, style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
                      ),
                    ),
                  )).toList(),
                ),
                const Spacer(),
                ElevatedButton.icon(
                  style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF0D9488), padding: const EdgeInsets.symmetric(vertical: 20)),
                  onPressed: (_selectedSide != null && _selectedView != null && !_isProcessing) ? _executeCapture : null,
                  icon: const Icon(Icons.camera, color: Colors.white, size: 28),
                  label: const Text('CAPTURE', style: TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.bold)),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}
